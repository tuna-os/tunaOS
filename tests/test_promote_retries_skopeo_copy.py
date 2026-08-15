"""Promotion copies must survive a dropped GHCR upload session.

Promote is the last thing that happens to a variant, and it is six to
sixteen full blob-for-blob re-uploads to GHCR back to back. On run
31891742138 (gurnard, 2026-08-15) five of them succeeded and the sixth --
the `elementary` alias -- died on::

    copying image 2/2 from manifest list: writing blob: uploading layer to
    https://ghcr.io/v2/tuna-os/elementary/blobs/upload/2.fbd191d4-...:
    blob upload unknown

GHCR had dropped the upload session. Under `set -e` that failed the job with
the canonical tags already written and one alias missing, and it was the
*first* thing to fail there in weeks -- Promote had been skipped wholesale
by the Sigstore outage (#1560) until the sign/attest split let it run at
all, so this surface had simply never been exercised.

The workflow already retries the two other network legs it depends on: the
base-image pull and the GHCR push. The promotion copies were the one bare
path left, which is what these tests pin.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"

STEP = "Pull Image and Apply Tags"


@pytest.fixture(scope="module")
def promote_step():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["tag-image"]["steps"]
    return next(s for s in steps if s.get("name") == STEP)


def test_no_promotion_copy_is_unguarded(promote_step):
    """Every destination goes through the wrapper, not just the one that broke.

    The alias copy failed first only because it runs last; every earlier copy
    is the same call to the same registry.
    """
    body = promote_step["run"]
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "skopeo copy" not in stripped:
            continue
        assert "copy_retry" in body, "no copy_retry helper defined at all"
        assert "if sudo skopeo copy" in stripped, (
            f"promotion copy outside the retry helper: {stripped!r}"
        )


def test_the_helper_is_used_for_canonical_tags_and_aliases(promote_step):
    """A retry that covers only some destinations leaves the same hole."""
    body = promote_step["run"]
    calls = re.findall(r"^\s*copy_retry .*$", body, re.M)
    assert len(calls) >= 6, f"expected every promotion destination wrapped, found {calls}"
    joined = "\n".join(calls)
    assert "${alias_name}" in joined, "the alias copies -- the ones that failed -- are not retried"
    assert "${DEFAULT_TAG}-${arch}" in joined, "the per-arch copies are not retried"


# ── The helper's own behaviour, driven directly ───────────────────────────


def _harness(promote_step, tmp_path: Path, skopeo_body: str, retries: str = "4"):
    """Run the real copy_retry from the workflow against a fake skopeo.

    The sleeps are real, so the fixtures below stay at one or two attempts.
    """
    body = promote_step["run"]
    start = body.index("copy_retry() {")
    end = body.index("\n}\n", start) + len("\n}\n")
    helper = body[start:end]

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sudo").write_text('#!/usr/bin/env bash\nexec "$@"\n')
    (bin_dir / "skopeo").write_text(f"#!/usr/bin/env bash\n{skopeo_body}\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)

    script = tmp_path / "probe.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'MAX_RETRIES={retries}\nSOURCE_IMAGE="ghcr.io/tuna-os/gurnard:latest-testing"\n'
        f"{helper}\n"
        'copy_retry "ghcr.io/tuna-os/elementary:latest" && echo PROMOTED\n'
    )
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        timeout=180,
    )


def test_a_dropped_upload_session_is_retried(promote_step, tmp_path):
    """The gurnard failure, replayed: fail once, succeed on the retry."""
    marker = tmp_path / "attempts"
    proc = _harness(
        promote_step,
        tmp_path,
        textwrap.dedent(
            f"""\
            n=0
            [[ -f "{marker}" ]] && n=$(cat "{marker}")
            n=$((n + 1)); echo "$n" > "{marker}"
            if [[ "$n" -lt 2 ]]; then
              echo 'level=fatal msg="copying image 2/2 from manifest list: writing blob: uploading layer to https://ghcr.io/v2/tuna-os/elementary/blobs/upload/2.fbd191d4: blob upload unknown"' >&2
              exit 1
            fi
            """
        ),
    )
    assert proc.returncode == 0, f"a recoverable copy still failed Promote: {proc.stderr!r}"
    assert "PROMOTED" in proc.stdout
    assert marker.read_text().strip() == "2"


def test_exhaustion_still_fails_the_job(promote_step, tmp_path):
    """A retry that swallows a real outage is worse than no retry.

    If every attempt fails, the bare tag was not written and Promote must say
    so -- otherwise users pull a tag that silently still points at yesterday.
    """
    proc = _harness(
        promote_step,
        tmp_path,
        'echo "blob upload unknown" >&2; exit 1',
        retries="2",
    )
    assert proc.returncode != 0, "every attempt failed and copy_retry reported success"
    assert "PROMOTED" not in proc.stdout
    assert "::error::" in proc.stdout + proc.stderr, "exhaustion is not surfaced as an error"


def test_the_helper_does_not_sleep_after_its_last_attempt(promote_step, tmp_path):
    """Dead sleep at the end buys nothing and lengthens every red run.

    The same defect cosign-retry.sh carried before #1748; pinned here so the
    two retry paths do not drift apart.
    """
    proc = _harness(promote_step, tmp_path, "exit 1", retries="1")
    assert proc.returncode != 0
    assert "retrying in" not in proc.stdout + proc.stderr, (
        "a single-attempt budget still slept before giving up"
    )
