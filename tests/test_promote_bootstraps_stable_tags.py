"""Promote writes :testing and the dated tags; the bare tags only for a new cell.

RFC 018 phase 3 moved the stable ring (the bare :<flavor>, :<flavor>-<arch>
and <alias>:<flavor> tags) to promote-stable.yml. Promote in
reusable-build-image.yml still writes them once, when the bare tag does not
exist yet, so a brand-new cell can be installed before its first soak ends.
These tests run the real "Pull Image and Apply Tags" step against a fake
skopeo and record which tags it writes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/reusable-build-image.yml"
REG = "ghcr.io/tuna-os"


@pytest.fixture(scope="module")
def promote_step():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    steps = workflow["jobs"]["tag-image"]["steps"]
    return next(s for s in steps if s.get("name") == "Pull Image and Apply Tags")


def promote(promote_step, tmp_path: Path, inspect: str, built: str = "true"):
    """Run the step. inspect is the fake `skopeo inspect` result for the bare
    tag: exists, missing or broken. Returns (process, copied destinations)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "copies"
    (bin_dir / "sudo").write_text('#!/usr/bin/env bash\nexec "$@"\n')
    (bin_dir / "date").write_text("#!/usr/bin/env bash\necho 20261030\n")
    (bin_dir / "skopeo").write_text(f"""#!/usr/bin/env bash
case "$1" in
  copy) echo "${{@: -1}}" >> "{log}" ;;
  inspect)
    case "{inspect}" in
      exists) echo '{{}}' ;;
      missing) echo 'manifest unknown: manifest unknown' >&2; exit 1 ;;
      *) echo 'connection reset by peer' >&2; exit 1 ;;
    esac ;;
esac
""")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    output = tmp_path / "output"
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "IMAGE_REGISTRY": REG, "IMAGE_NAME": "albacore", "IMAGE_ALIASES": "almalinux",
        "DEFAULT_TAG": "gnome", "ALL_PLATFORMS_BUILT": built,
        "INPUT_PLATFORMS": "linux/amd64,linux/arm64", "MAX_RETRIES": "1",
        "GITHUB_OUTPUT": str(output),
    }
    proc = subprocess.run(["bash", "-e", "-c", promote_step["run"]], check=False,
                          capture_output=True, text=True, env=env, timeout=120)
    copies = log.read_text().split() if log.exists() else []
    return proc, [c.removeprefix("docker://") for c in copies]


TESTING = [f"{REG}/albacore:gnome-testing", f"{REG}/albacore:gnome-20261030",
           f"{REG}/albacore:gnome-amd64-20261030", f"{REG}/albacore:gnome-arm64-20261030",
           f"{REG}/almalinux:gnome-20261030"]
STABLE = [f"{REG}/albacore:gnome", f"{REG}/albacore:gnome-amd64",
          f"{REG}/albacore:gnome-arm64", f"{REG}/almalinux:gnome"]


def test_an_existing_cell_gets_testing_and_dated_tags_only(promote_step, tmp_path):
    proc, copies = promote(promote_step, tmp_path, "exists")
    assert proc.returncode == 0, proc.stderr
    assert sorted(copies) == sorted(TESTING)


def test_a_new_cell_bootstraps_every_stable_tag_once(promote_step, tmp_path):
    proc, copies = promote(promote_step, tmp_path, "missing")
    assert proc.returncode == 0, proc.stderr
    assert sorted(copies) == sorted(TESTING + STABLE)
    assert "bootstrapping the stable tags" in proc.stdout


def test_an_unreadable_bare_tag_is_never_overwritten(promote_step, tmp_path):
    proc, copies = promote(promote_step, tmp_path, "broken")
    assert proc.returncode == 0, proc.stderr
    assert sorted(copies) == sorted(TESTING)
    assert "the stable tags are not bootstrapped" in proc.stdout


def test_an_incomplete_build_writes_nothing(promote_step, tmp_path):
    proc, copies = promote(promote_step, tmp_path, "missing", built="false")
    assert proc.returncode == 0, proc.stderr
    assert copies == []
