"""The protected-removal specification (#3803, F4b) must not drift from the repo.

The specification derives the protected set from contracts that exist. It must
not turn into a second catalog: every repository file it names must exist, every
package family that build_scripts/lib.sh can detect must have an adapter row,
and every failure code the text uses must be in the failure table. Removals stay
rejected; the rejection tests live in test_image_packages and
test_legacy_fork_migration and are not repeated here.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / ".spektacular/specs/20261024100000-protected-native-package-removal.md"
PLAN = ROOT / ".spektacular/plans/20261024100000-protected-native-package-removal/plan.md"
REJECTION_TESTS = {
    "tests/test_image_packages.py": "def test_removals_are_rejected_with_the_reason",
    "tests/test_legacy_fork_migration.py": "def test_unconvertible_legacy_input_fails_loudly_and_changes_nothing",
}


@lru_cache(maxsize=1)
def spec_text():
    assert SPEC.is_file(), SPEC.relative_to(ROOT)
    return SPEC.read_text(encoding="utf-8")


def clause(number):
    match = re.search(rf"^## [^\n]*\(`PR-{number}`\)\n(.*?)(?=^## |\Z)", spec_text(), re.M | re.S)
    assert match, f"PR-{number}"
    return match.group(1)


def test_clauses_are_numbered_once_in_order():
    ids = re.findall(r"^## [^\n]*\(`PR-(\d+)`\)$", spec_text(), re.M)
    assert ids == [str(number) for number in range(1, len(ids) + 1)]
    assert len(ids) >= 10


def test_every_cited_repository_file_exists():
    cited = set()
    for text in (spec_text(), PLAN.read_text(encoding="utf-8")):
        for token in re.findall(r"`([^`\s]+)`", text):
            if re.fullmatch(r"[\w./-]+\.(?:sh|py|toml|json|ya?ml)", token):
                cited.add(token)
    assert {"verify-base-contract.sh", "verify-desktop-experience.sh", "e2e-runtime-checks.sh"} <= cited
    missing = []
    for token in sorted(cited):
        found = (ROOT / token).is_file() if "/" in token else any(ROOT.rglob(token))
        if not found:
            missing.append(token)
    assert not missing, missing


def test_every_detected_package_family_has_an_adapter_row():
    lib = (ROOT / "build_scripts/lib.sh").read_text(encoding="utf-8")
    families = {match[1] for match in re.findall(r"""PKG_MGR\s*=\s*(['"])(\w+)\1""", lib)}
    assert families >= {"apt", "dnf", "pacman", "zypper", "emerge"}, families
    rows = [line.split("|")[1].strip().lower() for line in clause(6).splitlines() if line.startswith("| ") and "---" not in line]
    names = {"emerge": "portage"}
    assert all(any(names.get(family, family) in row for row in rows) for family in families), (families, rows)


def test_unsupported_family_rows_fail_closed():
    portage = [line for line in clause(6).splitlines() if line.startswith("| Portage")]
    assert len(portage) == 1 and "Unsupported" in portage[0] and "fails before mutation" in portage[0]


def test_every_failure_code_in_the_text_is_in_the_failure_table():
    table = clause(9)
    declared = set()
    for line in table.splitlines():
        if line.startswith("| `"):
            declared.update(re.findall(r"`([a-z-]+)`", line.split("|")[1]))
    assert {"schema", "conflict", "unsupported-family", "protected", "solver-unavailable",
            "dependency-induced", "contract-unowned", "plan-drift", "receipt-missing"} <= declared
    used = set(re.findall(r"with (?:code )?`([a-z]+(?:-[a-z]+)*)`", spec_text()))
    used |= set(re.findall(r"fails with `([a-z-]+)`", spec_text()))
    assert used <= declared, used - declared


def test_removal_stays_disabled_and_the_rejection_tests_exist():
    assert "does not enable package removal" in spec_text()
    assert "MUST continue\nto reject non-empty removal intent" in clause(1)
    assert "starts empty" in PLAN.read_text(encoding="utf-8")
    for path, marker in REJECTION_TESTS.items():
        assert marker in (ROOT / path).read_text(encoding="utf-8"), path


def test_no_checked_in_protected_name_list():
    assert "There MUST NOT be a checked-in list of package names" in clause(3)
    assert not list((ROOT / "config").rglob("*protected*")), "a protected-package list must not be committed"
