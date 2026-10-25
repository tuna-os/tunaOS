"""RFC 017 (#3803) is the decision record for the protected-removal specification.

The specification is normative (.spektacular, from #3855). The RFC must link it,
must cite only repository files that exist, and must keep the one table that the
specification does not carry: why the stock `pkg_remove` is unsafe for each
package family that build_scripts/lib.sh can detect. Removals stay rejected; the
rejection tests live in test_image_packages and test_legacy_fork_migration
and are not repeated here.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RFC = ROOT / "docs/rfc/rfc017-protected-package-removal.md"
SPEC_STEM = "20261024100000-protected-native-package-removal"


@lru_cache(maxsize=1)
def rfc_text():
    assert RFC.is_file(), f"RFC 017 is missing: {RFC.relative_to(ROOT)}"
    return RFC.read_text(encoding="utf-8")


def section(title):
    match = re.search(
        rf"^#+ {re.escape(title)}\n(.*?)(?=^#+ |\Z)",
        rfc_text(),
        re.M | re.S,
    )
    assert match, title
    return match.group(1)


def repository_files():
    """Repository file paths: `git ls-files`, or a directory walk without git or a .git."""
    try:
        listing = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
        return sorted(filter(None, listing.split("\0")))
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(ROOT).parts
        )


@lru_cache(maxsize=1)
def tracked_by_name():
    """Index repository files by basename, in sorted order."""
    index = {}
    for path in repository_files():
        index.setdefault(path.rsplit("/", 1)[-1], []).append(path)
    return index


def test_cited_files_exist():
    cited = set()
    for title in ("Current state", "One design"):
        for token in re.findall(r"`([^`\s]+)`", section(title)):
            path = token.split("::", 1)[0]
            if re.search(r"\.(?:sh|py|toml|json|ya?ml)$", path):
                if "/" in path:
                    cited.add(path)
                else:
                    matches = tracked_by_name().get(path, [])
                    assert matches, f"missing bare RFC reference: {path}"
                    assert len(matches) == 1, f"ambiguous bare RFC reference {path}: {matches}"
                    cited.add(matches[0])
    missing = sorted(p for p in cited if not (ROOT / p).is_file())
    assert cited and not missing, missing


def test_the_specification_is_linked_and_its_clauses_exist():
    # The specification arrives in #3855. Until it is on `main`, only the link
    # is checked; afterwards, every `PR-n` clause the RFC cites must exist.
    assert f".spektacular/specs/{SPEC_STEM}.md" in rfc_text()
    assert f".spektacular/plans/{SPEC_STEM}/plan.md" in rfc_text()
    spec = ROOT / f".spektacular/specs/{SPEC_STEM}.md"
    if spec.is_file():
        declared = set(re.findall(r"\(`(PR-\d+)`\)", spec.read_text(encoding="utf-8")))
        cited = set(re.findall(r"`(PR-\d+)`", rfc_text()))
        assert cited and cited <= declared, cited - declared


def test_every_detected_package_family_has_a_pkg_remove_row():
    lib = (ROOT / "build_scripts/lib.sh").read_text(encoding="utf-8")
    families = {match[1] for match in re.findall(r"""PKG_MGR\s*=\s*(['"])(\w+)\1""", lib)}
    assert families >= {"apt", "dnf", "pacman", "zypper", "emerge"}, families
    rows = set()
    for line in section("Current state").splitlines():
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        if cells and re.fullmatch(r"\w+", cells[0]):
            rows.add(cells[0])
    assert families <= rows, families - rows


def test_decisions_are_numbered_and_removal_stays_off():
    decisions = re.findall(r"^(\d+)\. \*\*", section("Decisions for the maintainer"), re.M)
    assert decisions == [str(number) for number in range(1, len(decisions) + 1)] and len(decisions) >= 8
    assert "Every removal stays rejected" in rfc_text()
    assert "does not enable a removal" in rfc_text()


def test_repository_files_falls_back_to_a_walk_without_git(monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    names = repository_files()
    assert "build_scripts/lib.sh" in names and not any(name.startswith(".git/") for name in names)
