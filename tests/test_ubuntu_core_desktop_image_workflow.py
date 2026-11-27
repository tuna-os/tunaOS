"""The Ubuntu Core Desktop image workflow builds and boots; it never publishes.

docs/UBUNTU-CORE-DESKTOP.md stage 2: `ubuntu-core-desktop-image.yml` builds
canonical/ubuntu-core-desktop at a pinned commit, boots a throwaway copy under
QEMU/KVM and keeps the result as an Actions artifact. Stage 3 (publishing) is
a decision the project owner has not taken, so the workflow must stay unable to
publish: the image is an unasserted `grade: dangerous` developer preview that
the Snap Store can never refresh.

These tests pin the shape that keeps that true, and the shape that makes the
gate worth running:

  * dispatch is the only trigger, so nothing builds a multi-gigabyte image on
    a schedule or a pull request that nobody asked for;
  * the token is `contents: read` and no step uses a secret, a release, a
    registry push or a Snap Store upload;
  * the kept image is built only after the boot gate, and the gate takes its
    pictures as PNG (qemu 10.2 shears PPM screendumps);
  * every snap a build.sh invocation names is a snap that was downloaded.

Falsification: structural -- add a `schedule:` or `push:` trigger, widen
`permissions`, add `gh release upload`, swap `format="png"` for `ppm`, move the
image build above the gate, or drop a downloaded snap, and a test below fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ubuntu-core-desktop-image.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
DOC = yaml.safe_load(TEXT)
# PyYAML resolves the bare key `on:` to the boolean True.
ON = DOC.get("on", DOC.get(True))
JOB = DOC["jobs"]["image"]
STEPS = {step["name"]: step for step in JOB["steps"]}
ORDER = [step["name"] for step in JOB["steps"]]


def _step(prefix: str) -> dict:
    (name,) = [n for n in STEPS if n.startswith(prefix)]
    return STEPS[name]


def _code() -> str:
    """The workflow without comment lines, which may name what is forbidden."""
    return "\n".join(line for line in TEXT.splitlines() if not line.lstrip().startswith("#"))


def test_dispatch_is_the_only_trigger():
    assert set(ON) == {"workflow_dispatch"}, (
        f"triggers are {sorted(ON)}; a scheduled or PR-triggered build would "
        "produce a multi-gigabyte image nobody asked for"
    )


def test_the_dispatch_inputs_are_the_documented_ones():
    inputs = ON["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"desktop", "upstream_ref", "gate"}
    assert inputs["desktop"]["type"] == "choice"
    assert inputs["desktop"]["options"] == ["gnome", "kde"]
    assert inputs["gate"]["type"] == "boolean"
    assert inputs["gate"]["default"] is True, "the gate is on unless someone turns it off"
    # A branch name would move under the manifest, so the default and the
    # validation step both insist on a full commit SHA.
    assert re.fullmatch(r"[0-9a-f]{40}", inputs["upstream_ref"]["default"])
    assert "{40}" in _step("Validate")["run"]


def test_the_token_can_only_read():
    assert DOC["permissions"] == {"contents": "read"}
    assert "permissions" not in JOB, "a job-level block could widen the token"


@pytest.mark.parametrize(
    "forbidden",
    [
        r"gh release (create|upload|edit)",
        r"gh api[^\n]*-X\s*(POST|PUT|PATCH|DELETE)",
        r"\bghcr\.io\b",
        r"\b(docker|podman|skopeo|oras)\s+(push|copy)\b",
        r"\bcosign\b",
        r"\bsnapcraft\b",
        r"\bsnap (login|upload|release)\b",
        r"\bsecrets\.",
        r"id-token",
        r"\bpackages:",
        r"contents:\s*write",
    ],
)
def test_nothing_in_the_workflow_can_publish(forbidden):
    assert not re.search(forbidden, _code()), f"workflow matches {forbidden!r}"


def test_it_runs_where_kvm_exists():
    # tests/test_kvm_jobs_run_where_kvm_exists.py states the rule: KVM only on
    # GitHub-hosted ubuntu-* runners, never on the ARC or EC2 pools.
    assert "/dev/kvm" in TEXT
    assert str(JOB["runs-on"]).startswith("ubuntu-")


def test_the_kept_image_is_built_only_after_the_boot_gate():
    gate_build = ORDER.index("Build the gate image")
    gate_boot = ORDER.index(_step("Boot gate")["name"])
    final = ORDER.index("Build the image")
    assert gate_build < gate_boot < final
    for name in ("Build the gate image", _step("Boot gate")["name"]):
        assert STEPS[name]["if"] == "inputs.gate"
    assert "if" not in STEPS["Build the image"], (
        "the kept image must not be conditional: gate=false skips the gate, "
        "it does not skip the build"
    )


def test_the_gate_boots_twice_and_takes_png_pictures():
    run = _step("Boot gate")["run"]
    assert "snapd.seeded" in run, "the cold boot must wait for seeding"
    assert "pgrep -x $shell" in run and "gnome-shell" in run and "plasmashell" in run
    assert run.index("cold boot") < run.index("warm boot")
    assert 'format="png"' in run
    assert "ppm" not in _code().lower(), "qemu 10.2 shears PPM screendumps"


def test_the_artifacts_are_short_lived_and_carry_the_checksums_and_manifest():
    uploads = [s for s in JOB["steps"] if "upload-artifact" in str(s.get("uses", ""))]
    assert len(uploads) == 2
    image, evidence = uploads
    # tests/test_no_workflow_hoards_multi_gigabyte_artifacts.py: one day, and
    # no recompression of an already compressed image.
    assert image["with"]["retention-days"] == 1
    assert str(image["with"]["compression-level"]) == "0"
    paths = image["with"]["path"]
    assert ".img.zst" in paths and "SHA256SUMS" in paths and "manifest.txt" in paths
    # The pictures are the point of the gate; keep them when the gate fails.
    assert evidence["if"] == "always()"
    assert evidence["with"]["path"].strip() == "evidence/"


@pytest.mark.parametrize("desktop", ["gnome", "kde"])
def test_every_snap_a_build_names_was_downloaded(desktop):
    run = _step("Download")["run"]
    branch = run.split("kde)")[1] if desktop == "kde" else run.split("kde)")[0].split("gnome)")[1]
    downloaded = set(re.findall(r"^\s+\S+/\S+?:\S+?:(\S+\.snap)$", branch, re.M))
    named = set(re.findall(r"^\s*snaps/(\S+\.snap)$", branch, re.M))
    # The base is downloaded after the specs, under its own local name.
    downloaded.add("core26-desktop-variant.snap")
    assert named, f"no snaps named in the {desktop} build-args"
    assert named == downloaded, (
        f"{desktop}: named but never downloaded {sorted(named - downloaded)}, "
        f"downloaded but never used {sorted(downloaded - named)}"
    )
