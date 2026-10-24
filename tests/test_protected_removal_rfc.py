"""RFC 017 (#3803) derives protected packages from contracts that exist.

The specification must not drift into a second catalog: every repository file
it names as a source or a current rejection must exist, and every package
family that build_scripts/lib.sh can detect must have its own evidence row.
Removals stay rejected; the rejection tests live in test_fork_config_consumers
and test_fork_package_consumer and are not repeated here.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RFC = ROOT / "docs/rfc/rfc017-protected-package-removal.md"
assert RFC.is_file(), f"RFC 017 is missing: {RFC.relative_to(ROOT)}"
TEXT = RFC.read_text(encoding="utf-8")


def section(title):
    match = re.search(rf"^#+ {re.escape(title)}\n(.*?)(?=^#+ |\Z)", TEXT, re.M | re.S)
    assert match, title
    return match.group(1)


def test_cited_contract_files_exist():
    cited = set()
    for title in ("Current state", "Sources", "Gaps in the contracts", "Removal boundary"):
        for token in re.findall(r"`([^`\s]+)`", section(title)):
            path = token.split("::", 1)[0]
            if re.search(r"\.(?:sh|py|toml|json|ya?ml)$", path):
                has_glob = any(character in path for character in "*?[")
                if "/" in path:
                    matches = [
                        candidate for candidate in (
                            ROOT.glob(path) if has_glob else (ROOT / path,)
                        ) if candidate.is_file()
                    ]
                else:
                    matches = [candidate for candidate in ROOT.rglob(path) if candidate.is_file()]
                if has_glob:
                    assert matches, path
                    cited.update(candidate.relative_to(ROOT).as_posix() for candidate in matches)
                    continue
                if "/" not in path:
                    assert matches, f"missing bare RFC reference: {path}"
                    assert len(matches) == 1, (
                        f"ambiguous bare RFC reference {path}: "
                        + ", ".join(candidate.relative_to(ROOT).as_posix() for candidate in matches)
                    )
                    path = matches[0].relative_to(ROOT).as_posix()
                cited.add(path)
    # Paths that only exist in the open #3739 branch are named as such in the text.
    pending = {"tests/test_image_packages.py"}
    missing = sorted(p for p in cited - pending if not (ROOT / p).is_file())
    assert cited and not missing, missing


def test_every_detected_package_family_has_an_evidence_row():
    lib = (ROOT / "build_scripts/lib.sh").read_text(encoding="utf-8")
    families = set(re.findall(r'PKG_MGR="(\w+)"', lib))
    assert families >= {"apt", "dnf", "pacman", "zypper", "emerge"}, families
    rows = set(re.findall(r"^\|\s*(\w+)\s*\|\s*`", section("Approval boundary and evidence"), re.M))
    assert families <= rows, families - rows
