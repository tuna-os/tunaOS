"""Meta-tests validating the failure-injection test suite structure and coverage.

Ensures every incident in .github/green-criteria.yml and issue #2258 is covered
and all 5 invariant properties are systematically exercised.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml

from tests.injection.helpers import ROOT, load_green_criteria

INJECTION_DIR = ROOT / "tests" / "injection"

REQUIRED_TEST_MODULES = [
    "test_base_image_gc.py",
    "test_package_repo_outage.py",
    "test_declared_arch_missing.py",
    "test_requested_package_missing.py",
    "test_sigstore_rekor_outage.py",
    "test_qemu_boot_timeout.py",
    "test_push_failure.py",
    "test_disk_full.py",
]

FIVE_INVARIANTS = [
    "property_1",  # (1) Fails
    "property_2",  # (2) Says why
    "property_3",  # (3) Does not call the cell green
    "property_4",  # (4) Does not promote
    "property_5",  # (5) Keeps enough evidence to diagnose
]


def test_all_required_injection_modules_exist():
    """Verify all required failure-injection modules exist in tests/injection/."""
    for mod_name in REQUIRED_TEST_MODULES:
        mod_path = INJECTION_DIR / mod_name
        assert mod_path.is_file(), f"Missing required failure-injection module: {mod_name}"


@pytest.mark.parametrize("mod_name", REQUIRED_TEST_MODULES)
def test_modules_cover_five_invariants(mod_name):
    """Verify each failure-injection module contains test functions addressing the 5 properties."""
    mod_path = INJECTION_DIR / mod_name
    content = mod_path.read_text(encoding="utf-8")

    # Verify docstring mentions all 5 properties
    for prop in ["(1)", "(2)", "(3)", "(4)", "(5)"]:
        assert prop in content, f"{mod_name} must document property {prop} in docstring or tests"

    # Verify functions targeting properties exist
    assert "test_property_1" in content or "test_property_1_and_2" in content
    assert "test_property_3" in content
    assert "test_property_4" in content
    assert "test_property_5" in content


def test_green_criteria_incidents_are_referenced():
    """Verify incidents mentioned in green-criteria.yml have tests in tests/injection/."""
    criteria = load_green_criteria()
    # Ensure green-criteria.yml loaded properly
    assert len(criteria) > 0
    assert any(c["id"] == "builds" for c in criteria)

    # Collect all text in tests/injection
    all_test_code = ""
    for p in INJECTION_DIR.glob("*.py"):
        all_test_code += p.read_text(encoding="utf-8") + "\n"

    # Specific historical incident numbers from green-criteria.yml / issue #2258
    key_incidents = ["1788", "391", "1755", "858", "1560", "1811"]
    for inc in key_incidents:
        assert inc in all_test_code, f"Incident #{inc} must be explicitly referenced in failure-injection suite"
