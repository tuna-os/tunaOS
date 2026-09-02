"""When the scan dies, the SBOM should come from the manifest, not from nowhere.

`Generate SBOM` scans the built image with syft. On guppy it reliably does not
survive that: Gentoo's file inventory outgrows the runner, and since #1784 the
cgroup cap kills syft rather than letting it take the runner agent down with
it. That was the right trade -- the variant builds, signs and promotes -- but
it left guppy publishing no SBOM at all, and `Attest SBOM` reporting the gap
every night.

The data was never missing. `Publish package manifest` runs two steps earlier
and reads the whole installed-package list straight out of the image's own
package database, in seconds. Re-deriving that same list by walking every file
in the image is precisely what costs the memory.

These tests pin the fallback: the generator that turns a manifest into SPDX,
and the wiring that makes it fire only when the scan did not.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"
GENERATOR = ROOT / "scripts/packages_to_spdx.py"

sys.path.insert(0, str(ROOT / "scripts"))
import packages_to_spdx as gen  # noqa: E402


@pytest.fixture(scope="module")
def build_push():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["build_push"]


def step(build_push, name):
    return next(s for s in build_push["steps"] if s.get("name") == name)


def run_generator(tmp_path, manifest_text, *, image="ghcr.io/tuna-os/guppy:latest-linux-amd64"):
    manifest = tmp_path / "packages.txt"
    manifest.write_text(manifest_text, encoding="utf-8")
    out = tmp_path / "sbom.spdx.json"
    proc = subprocess.run(
        [
            sys.executable, str(GENERATOR),
            "--manifest", str(manifest),
            "--output", str(out),
            "--image", image,
            "--created", "2026-08-16T13:00:00Z",
        ],
        capture_output=True,
        text=True,
    )
    return proc, out


# ── every package manager the manifest step can emit ──────────────────────


@pytest.mark.parametrize(
    "line,expected",
    [
        # rpm / dpkg / pacman all reach the manifest as name<TAB>version.
        ("bash\t5.2.26-3.fc42", ("bash", "5.2.26-3.fc42")),
        ("libc6\t2.40-1", ("libc6", "2.40-1")),
        # portage arrives as a bare atom from `qlist -ICv`, single column.
        ("app-editors/vim-9.1.0", ("vim", "9.1.0")),
        # The version starts at the last hyphen followed by a digit, so a
        # name that merely contains digits after a hyphen is not split there.
        ("dev-libs/libx86-1.1", ("libx86", "1.1")),
        # Gentoo revisions are part of the version, not a second package.
        ("sys-apps/portage-3.0.66-r1", ("portage", "3.0.66-r1")),
        # `+` is legal in a package name and must survive parsing.
        ("x11-libs/gtk+-3.24.43", ("gtk+", "3.24.43")),
    ],
)
def test_the_parser_handles_every_manifest_format_the_build_produces(line, expected):
    """One generator serves rpm, dpkg, pacman and portage editions alike.

    The manifest step already normalises four package managers into two
    shapes; anything it can write, this has to read.
    """
    assert gen.parse_manifest(line) == [expected]


def test_a_version_we_did_not_read_is_not_invented():
    """NOASSERTION is a real SPDX value and an honest one; a guess is neither."""
    assert gen.parse_manifest("mystery-package") == [("mystery-package", "NOASSERTION")]


# ── the document has to be valid SPDX, not merely valid JSON ──────────────


def test_the_document_passes_the_same_checks_the_scan_path_is_held_to(tmp_path):
    """A consumer cannot tell which producer ran, so neither may ship less.

    These are the two `jq -e` assertions the workflow makes on syft's output,
    restated against the fallback's.
    """
    proc, out = run_generator(tmp_path, "bash\t5.2.26\napp-editors/vim-9.1.0\n")
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(out.read_text())
    assert doc["spdxVersion"].startswith("SPDX-")
    assert len(doc["packages"]) > 0


def test_spdx_ids_are_legal_and_unique(tmp_path):
    """SPDX 2.3 allows only letters, digits, `.` and `-` after `SPDXRef-`.

    `+` is not in that set, so `x11-libs/gtk+` cannot be used verbatim -- and
    sanitizing without disambiguating would collide `gtk+` with `gtk-`.
    """
    proc, out = run_generator(
        tmp_path, "x11-libs/gtk+-3.24.43\nx11-libs/gtk~-1.0\nsys-libs/glibc-2.40\n"
    )
    assert proc.returncode == 0, proc.stderr
    ids = [p["SPDXID"] for p in json.loads(out.read_text())["packages"]]
    for spdx_id in ids:
        assert re.fullmatch(r"SPDXRef-[-.a-zA-Z0-9]+", spdx_id), f"illegal SPDXID {spdx_id!r}"
    assert len(ids) == len(set(ids)), "two packages share an SPDXID"


def test_the_document_admits_what_it_is(tmp_path):
    """A package-level fallback must not read as a completed filesystem scan.

    `filesAnalyzed: true` with no files listed would be a false claim, and a
    consumer diffing this against a syft SBOM deserves to know why the file
    inventory is absent.
    """
    proc, out = run_generator(tmp_path, "bash\t5.2.26\n")
    doc = json.loads(out.read_text())
    assert all(p["filesAnalyzed"] is False for p in doc["packages"])
    assert "package database" in doc["creationInfo"]["comment"]


# ── refusing is better than lying ─────────────────────────────────────────


def test_a_marker_manifest_yields_no_sbom_rather_than_an_empty_one(tmp_path):
    """Some images ship no package database at all (tunaos-packages#135).

    The manifest step writes a comment marker for those. A zero-package SPDX
    document would assert that the image contains nothing, which is a
    stronger and more wrong claim than publishing no document.
    """
    proc, out = run_generator(
        tmp_path,
        "# NO PACKAGE DATABASE IN IMAGE\n# ghcr.io/tuna-os/guppy:latest\n",
    )
    assert proc.returncode != 0
    assert not out.exists(), "an empty SBOM was written anyway"


def test_a_missing_manifest_is_an_error_not_a_silent_success(tmp_path):
    proc = subprocess.run(
        [
            sys.executable, str(GENERATOR),
            "--manifest", str(tmp_path / "nope.txt"),
            "--output", str(tmp_path / "sbom.json"),
            "--image", "img",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert not (tmp_path / "sbom.json").exists()


# ── the wiring: fallback, not replacement ─────────────────────────────────


def test_the_fallback_runs_only_when_the_scan_did_not_produce_one(build_push):
    """syft's output is richer where it works; this only covers where it does not."""
    cond = step(build_push, "Synthesize SBOM from the package manifest")["if"]
    assert "steps.sbom.outcome != 'success'" in cond, (
        "the fallback does not check whether the scan already succeeded"
    )


def test_the_fallback_cannot_fail_the_variant_either(build_push):
    """It exists to recover a soft failure; it must not convert one into a hard one."""
    assert step(build_push, "Synthesize SBOM from the package manifest")["continue-on-error"] is True


def test_the_fallback_validates_its_own_output(build_push):
    """Producing an unusable file is not better than producing none."""
    run = step(build_push, "Synthesize SBOM from the package manifest")["run"]
    assert ".spdxVersion | startswith(\"SPDX-\")" in run
    assert "(.packages // []) | length > 0" in run


def test_the_fallback_refuses_a_missing_manifest(build_push):
    """`Publish package manifest` is continue-on-error, so the file may not exist."""
    run = step(build_push, "Synthesize SBOM from the package manifest")["run"]
    assert '[ ! -s "$MANIFEST" ]' in run, "the fallback does not check the manifest exists"


def test_either_producer_satisfies_the_upload(build_push):
    """Both write the same filename and meet the same bar; the upload should not care.

    Pinning only `steps.sbom.outcome` here would leave the fallback writing a
    valid SBOM that nothing ever uploads -- the failure mode the fallback was
    added to remove, restored one step later.
    """
    cond = step(build_push, "Upload SBOM")["if"]
    assert "steps.sbom.outcome == 'success'" in cond
    assert "steps.sbom_fallback.outcome == 'success'" in cond


def test_both_producers_agree_on_the_filename(build_push):
    """The upload globs `sbom-*.spdx.json`; a differently-named file is invisible."""
    scan = step(build_push, "Generate SBOM")["run"]
    fallback = step(build_push, "Synthesize SBOM from the package manifest")["run"]
    name = 'OUT="sbom-${IMAGE_NAME}-${DEFAULT_TAG}-${SAFE_PLATFORM}.spdx.json"'
    assert name in scan
    assert name in fallback
