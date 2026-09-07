"""Regression tests for the manifest package-source policy."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_package_sources", ROOT / "scripts" / "check-package-sources.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_forbidden_source_keys_are_reported():
    errors = MODULE.violations({"desktop": {"copr": ["example/project"]}})
    assert errors == ["desktop.copr: copr is not an approved package source"]


def test_tideforge_and_system_urls_are_allowed():
    assert MODULE.violations({"repo": {"baseurl": "https://repo.tunaos.org/desktop/"}}) == []
    assert MODULE.violations({"repo": {"baseurl": "https://tideforge.org/v1/"}}) == []


def test_lookalike_hosts_are_not_allowed():
    errors = MODULE.violations({"repo": {"baseurl": "https://repo.tunaos.org.attacker.invalid/"}})
    assert len(errors) == 1
    assert "not approved" in errors[0]


def _repo(tmp_path, manifest_text, base_text=None):
    """A throwaway git repo with a manifest, optionally with a baseline commit."""
    import subprocess

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                       capture_output=True)

    manifest = tmp_path / "manifests" / "desktops" / "example.yaml"
    manifest.parent.mkdir(parents=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    if base_text is not None:
        manifest.write_text(base_text)
        git("add", "-A")
        git("commit", "-qm", "base")
    else:
        (tmp_path / ".gitkeep").write_text("")
        git("add", "-A")
        git("commit", "-qm", "empty")
    manifest.write_text(manifest_text)
    git("add", "-A")
    git("commit", "-qm", "change")
    return manifest


def _run(tmp_path, base="HEAD~1"):
    """Invoke the checker's main() with cwd inside the throwaway repo."""
    import os
    import sys

    cwd = os.getcwd()
    argv = sys.argv
    os.chdir(tmp_path)
    sys.argv = ["check-package-sources.py", "--base", base]
    try:
        return MODULE.main()
    finally:
        os.chdir(cwd)
        sys.argv = argv


GRANDFATHERED = """
packages:
  el10:
    copr:
      - repo: legacy/backport
"""


def test_a_pre_existing_source_does_not_fail_an_unrelated_edit(tmp_path):
    """The gate blocks what a change ADDS, not what its file already had.

    PACKAGE-SOURCING.md §Enforcement: the CI check "blocks new manifest
    changes that add COPR, PPA, OBS, AUR, or an unapproved repository URL",
    and "existing legacy declarations remain migration inventory". Adding an
    unrelated `eln:` section to manifests/desktops/gnome.yaml used to fail on
    `packages.el10.copr` — a block the diff never touched, on main since
    before this script existed.
    """
    changed = GRANDFATHERED + """  eln:
    packages:
      - gnome-shell
"""
    _repo(tmp_path, changed, base_text=GRANDFATHERED)
    assert _run(tmp_path) == 0


def test_a_newly_added_source_still_fails(tmp_path):
    """The exemption is for what was already there, and nothing else."""
    changed = GRANDFATHERED + """  eln:
    copr:
      - repo: someone/new-thing
"""
    _repo(tmp_path, changed, base_text=GRANDFATHERED)
    assert _run(tmp_path) == 1


def test_a_brand_new_manifest_is_checked_in_full(tmp_path):
    """No baseline means no grandfathering — every source in it is new."""
    _repo(tmp_path, GRANDFATHERED, base_text=None)
    assert _run(tmp_path) == 1


def test_moving_an_existing_block_is_not_an_addition(tmp_path):
    """Documents are compared parsed, so a reformat is not a new source.

    A line-based diff would call the re-indented block an addition and fail
    a change that added no source at all.
    """
    reformatted = """
packages:
  el10: {copr: [{repo: legacy/backport}]}
"""
    _repo(tmp_path, reformatted, base_text=GRANDFATHERED)
    assert _run(tmp_path) == 0
