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
