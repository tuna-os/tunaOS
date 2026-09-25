"""tunaOS#2697: the SBOM attestation never succeeded, because every SBOM was too large for Rekor.

rekor.sigstore.dev refuses a request body over 24 MiB with "502 Bad Gateway"
(measured 2026-09-25: 24117352 bytes got a 400 from Rekor, 25165928 bytes got
the 502). Syft's SPDX SBOMs list every file that every package owns. Bonito
base-rawhide was 37.9 MB, kde-nvidia-rawhide was 122.7 MB. So every
`cosign attest` got a 502, used its 10m budget, and reported SIGSTORE_OUTAGE.
Meanwhile `cosign sign` uploaded to the same log in the same minutes (Build
Albacore 35970880514: 17/17 Sign passed, 17/17 Attest SBOM failed).

The same runs showed a second defect. A failed `Upload SBOM` (DNS error,
job 107608521404) failed build_push, and niri-hwe's Sign, Gate and Promote
were skipped although Manifest found all three platforms.

Falsification: behavioural for the size. The tests run
.github/scripts/sbom-for-rekor.sh on a generated SPDX document with a large
per-file inventory. On the unfixed tree the script does not exist, so those
tests fail. Structural for the wiring: revert the `--predicate "$predicate"`
change in attest-sbom.yml, or remove `continue-on-error` from `Upload SBOM`,
and the last two tests fail.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/sbom-for-rekor.sh"
ATTEST = ROOT / ".github/workflows/attest-sbom.yml"
BUILD = ROOT / ".github/workflows/reusable-build-image.yml"
REKOR_LIMIT = 24 * 1024 * 1024


def _spdx(packages: int, files_per_package: int) -> dict:
    """A document shaped like Syft's output: packages, owned files, CONTAINS edges."""
    doc = {
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "ghcr.io/tuna-os/bonito:base-rawhide",
        "packages": [],
        "files": [],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": "SPDXRef-Package-0",
                "relationshipType": "DESCRIBES",
            }
        ],
    }
    for p in range(packages):
        pid = f"SPDXRef-Package-{p}"
        doc["packages"].append(
            {
                "SPDXID": pid,
                "name": f"pkg{p}",
                "versionInfo": "1.0-1",
                "filesAnalyzed": True,
                "packageVerificationCode": {"packageVerificationCodeValue": "0" * 40},
                "hasFiles": [],
            }
        )
        if p:
            doc["relationships"].append(
                {
                    "spdxElementId": f"SPDXRef-Package-{p - 1}",
                    "relatedSpdxElement": pid,
                    "relationshipType": "DEPENDENCY_OF",
                }
            )
        for f in range(files_per_package):
            fid = f"SPDXRef-File-{p}-{f}"
            doc["files"].append(
                {
                    "SPDXID": fid,
                    "fileName": f"/usr/lib/pkg{p}/file{f}.so",
                    "checksums": [{"algorithm": "SHA256", "checksumValue": "a" * 64}],
                }
            )
            doc["packages"][-1]["hasFiles"].append(fid)
            doc["relationships"].append(
                {"spdxElementId": pid, "relatedSpdxElement": fid, "relationshipType": "CONTAINS"}
            )
    return doc


def _run(tmp_path: Path, doc: dict, limit: int | None = None):
    src = tmp_path / "in.spdx.json"
    dst = tmp_path / "out.spdx.json"
    src.write_text(json.dumps(doc))
    env = dict(os.environ)
    if limit is not None:
        env["REKOR_PREDICATE_MAX_BYTES"] = str(limit)
    proc = subprocess.run(
        ["bash", str(SCRIPT), str(src), str(dst)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    return proc, src, dst


def test_the_attested_sbom_keeps_the_packages_and_drops_the_file_inventory(tmp_path):
    doc = _spdx(packages=40, files_per_package=200)
    proc, src, dst = _run(tmp_path, doc, limit=200_000)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(dst.read_text())

    assert src.stat().st_size > 5 * dst.stat().st_size, (
        f"{src.stat().st_size} -> {dst.stat().st_size} bytes: the per-file inventory is still there"
    )
    assert [p["name"] for p in out["packages"]] == [p["name"] for p in doc["packages"]]
    assert not out.get("files")
    kinds = sorted({r["relationshipType"] for r in out["relationships"]})
    assert kinds == ["DEPENDENCY_OF", "DESCRIBES"], kinds
    assert sum(r["relationshipType"] == "DEPENDENCY_OF" for r in out["relationships"]) == 39

    # SPDX 2.3: without files, filesAnalyzed is false and there is no
    # verification code or hasFiles list pointing at removed elements.
    for p in out["packages"]:
        assert p["filesAnalyzed"] is False
        assert "packageVerificationCode" not in p
        assert "hasFiles" not in p
    known = {p["SPDXID"] for p in out["packages"]} | {out["SPDXID"]}
    dangling = {
        e
        for r in out["relationships"]
        for e in (r["spdxElementId"], r["relatedSpdxElement"])
        if e not in known
    }
    assert not dangling, f"relationships point at removed elements: {sorted(dangling)[:3]}"


def test_an_sbom_still_too_large_fails_with_its_size_not_as_an_outage(tmp_path):
    doc = _spdx(packages=400, files_per_package=1)
    proc, _, _ = _run(tmp_path, doc, limit=1_000)
    assert proc.returncode != 0, "an SBOM over the limit was passed to cosign"
    assert "bytes" in proc.stderr and "24 MiB" in proc.stderr, proc.stderr
    # rerun-infra-failures.yml re-runs on this marker; a size failure never recovers.
    assert "SIGSTORE_OUTAGE" not in proc.stdout + proc.stderr


def test_the_default_limit_leaves_room_for_the_encoding():
    """cosign base64-encodes the predicate; some entry types encode it twice."""
    text = SCRIPT.read_text()
    default = int(text.split("REKOR_PREDICATE_MAX_BYTES:=", 1)[1].split("}", 1)[0])
    assert default * (4 / 3) * (4 / 3) < REKOR_LIMIT, (
        f"a {default}-byte predicate, base64-encoded twice, exceeds Rekor's 24 MiB limit"
    )


def test_attest_sbom_passes_the_package_level_sbom_to_cosign():
    attest = yaml.safe_load(ATTEST.read_text())
    run = next(
        s for s in attest["jobs"]["attest"]["steps"] if s.get("name") == "Attest SPDX SBOMs"
    )["run"]
    assert "sbom-for-rekor.sh" in run
    assert '--predicate "$predicate"' in run
    assert '--predicate "$sbom"' not in run, "the full Syft SBOM still goes to Rekor"


def test_a_failed_sbom_upload_does_not_fail_the_build_job():
    build_push = yaml.safe_load(BUILD.read_text())["jobs"]["build_push"]
    upload = next(s for s in build_push["steps"] if s.get("name") == "Upload SBOM")
    assert upload.get("continue-on-error") is True, (
        "a failed SBOM upload fails build_push, which skips Sign, Gate and Promote"
    )
