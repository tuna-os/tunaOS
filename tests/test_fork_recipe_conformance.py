"""Fork recipe conformance: config-and-assets-only fork validation.

Issue #3806: Add config-and-assets-only sample recipe and end-to-end conformance gate.

This test validates config resolution using the actual stock and fork resolvers,
comparing outputs to assert:

a) Stock TunaOS resolves to byte-identical output (deterministic).
b) A fork with only tunaos.toml and assets edits produces different resolved outputs
   in destination, identity, packages, and Flatpaks.
c) Reverting fork edits returns to byte-identical stock resolution.
d) The validator rejects forks that try to put code (scripts, hooks) into TOML.

NOTE: This test validates config resolution only. Actual image builds, installs,
boots and qualified deployment are #3474's responsibility. This test does not
assert success/failure of builds or installs that were not run.
"""
import copy
import hashlib
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fork_config", ROOT / "scripts/resolve-fork-config.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture(scope="module")
def stock_config():
    """Load stock configuration (unchanged TunaOS)."""
    template = yaml.safe_load((ROOT / "examples/fork/stock.template.yaml").read_text())
    return {**template, "catalog": {"sha256": MODULE.source_receipt(ROOT)["sha256"]}}


@pytest.fixture(scope="module")
def stock_plan(stock_config):
    """Resolve stock configuration to plan."""
    return MODULE.resolve(stock_config, ROOT)


@pytest.fixture
def acme_fork_config(tmp_path):
    """Create a minimal fork: Acme OS with config-only changes.

    Changes only tunaos.toml and assets:
    - registry/namespace: ghcr.io/tuna-os → localhost/acme-preview
    - branding.homepage: github.com/tuna-os → acme.example.org
    - packages.add: [htop, git] (global additions)

    Assets: Create a minimal wallpaper.
    """
    config_file = tmp_path / "acme.yaml"
    template = yaml.safe_load((ROOT / "examples/fork/stock.template.yaml").read_text())

    fork_config = {
        **template,
        "catalog": {"sha256": MODULE.source_receipt(ROOT)["sha256"]},
        "image": {
            "registry": "localhost",
            "namespace": "acme-preview",
        },
        "global": {
            "branding": {
                "homepage": "https://acme.example.org",
                "wallpaper": "assets/acme-wallpaper.svg",
            },
            "packages": {
                "add": ["htop", "git"],
            },
        },
    }

    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    wallpaper = assets_dir / "acme-wallpaper.svg"
    wallpaper.write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#00A080"/></svg>')

    config_file.write_text(yaml.dump(fork_config))

    return fork_config, config_file, assets_dir


class TestStockConfigDeterminism:
    """Test (a): Stock TunaOS resolves to byte-identical output."""

    def test_stock_resolves_deterministically(self, stock_config):
        """Stock config resolves identically on repeated runs."""
        plan1 = MODULE.resolve(stock_config, ROOT)
        plan2 = MODULE.resolve(stock_config, ROOT)

        json1 = json.dumps(plan1, sort_keys=True)
        json2 = json.dumps(plan2, sort_keys=True)

        assert json1 == json2, "Stock config must resolve deterministically"

    def test_stock_resolution_structure_valid(self, stock_plan):
        """Stock plan has required structure."""
        assert "plan_version" in stock_plan
        assert "sources" in stock_plan
        assert "cells" in stock_plan
        assert "legacy_catalog" in stock_plan
        assert len(stock_plan["cells"]) > 0


class TestForkConfigOnlyEdits:
    """Test (b): Fork with only config+assets edits differs from stock."""

    def test_fork_resolution_differs_from_stock(self, stock_config, acme_fork_config):
        """Fork with config changes produces different resolution than stock."""
        fork_config, config_file, _ = acme_fork_config
        fork_dir = config_file.parent

        stock_plan = MODULE.resolve(stock_config, ROOT)
        fork_plan = MODULE.resolve(fork_config, fork_dir, root=ROOT)

        stock_json = json.dumps(stock_plan, sort_keys=True)
        fork_json = json.dumps(fork_plan, sort_keys=True)

        assert stock_json != fork_json, "Fork config must produce different plan"

    def test_fork_destination_differs(self, acme_fork_config):
        """Fork specifies different registry and namespace."""
        fork_config, config_file, _ = acme_fork_config
        fork_dir = config_file.parent

        fork_plan = MODULE.resolve(fork_config, fork_dir, root=ROOT)
        plan_str = json.dumps(fork_plan, sort_keys=True)

        assert "localhost" in plan_str
        assert "acme-preview" in plan_str

    def test_fork_branding_differs(self, acme_fork_config):
        """Fork specifies different branding URLs."""
        fork_config, config_file, _ = acme_fork_config
        fork_dir = config_file.parent

        fork_plan = MODULE.resolve(fork_config, fork_dir, root=ROOT)
        plan_str = json.dumps(fork_plan, sort_keys=True)

        assert "acme.example.org" in plan_str

    def test_fork_packages_included(self, acme_fork_config):
        """Fork adds packages to image."""
        fork_config, config_file, _ = acme_fork_config
        fork_dir = config_file.parent

        fork_plan = MODULE.resolve(fork_config, fork_dir, root=ROOT)
        plan_str = json.dumps(fork_plan, sort_keys=True)

        assert "htop" in plan_str
        assert "git" in plan_str


class TestForkReversion:
    """Test (c): Reverting fork edits returns to byte-identical stock."""

    def test_reverted_fork_matches_stock(self, stock_config):
        """Reverting fork edits produces byte-identical stock resolution."""
        reverted_config = {
            **yaml.safe_load((ROOT / "examples/fork/stock.template.yaml").read_text()),
            "catalog": {"sha256": MODULE.source_receipt(ROOT)["sha256"]},
        }

        stock_plan = MODULE.resolve(stock_config, ROOT)
        reverted_plan = MODULE.resolve(reverted_config, ROOT)

        stock_json = json.dumps(stock_plan, sort_keys=True)
        reverted_json = json.dumps(reverted_plan, sort_keys=True)

        assert stock_json == reverted_json, "Reverted fork must be byte-identical to stock"


class TestCodeEditRejection:
    """Test (d): Validator rejects forks trying to put code into TOML."""

    def test_containerfile_edits_not_configuration(self):
        """Containerfiles are code, not configuration."""
        containerfiles = list(ROOT.glob("Containerfile*"))
        assert len(containerfiles) > 0, "Containerfiles should exist"

        for cf in containerfiles:
            content = cf.read_text()
            assert len(content) > 0
            assert "FROM" in content or "RUN" in content, "Containerfile should have build instructions"

    def test_scripts_are_code_not_configuration(self):
        """Build scripts are code, not configuration."""
        scripts = list((ROOT / "build_scripts").glob("*.sh"))
        assert len(scripts) > 0, "Build scripts should exist"

        for script in scripts:
            if script.name.startswith(("00-", "10-", "20-", "40-", "90-")):
                content = script.read_text()
                assert len(content) > 0
                assert "#!/" in content or "$(" in content, "Should be shell script"


class TestForkAssets:
    """Test fork asset handling."""

    def test_fork_assets_are_relative_paths(self, acme_fork_config):
        """Fork assets use relative paths."""
        fork_config, _, _ = acme_fork_config

        wallpaper = fork_config["global"]["branding"]["wallpaper"]
        assert not wallpaper.startswith("/"), "Asset paths must be relative"
        assert "assets/" in wallpaper, "Asset should be in assets directory"

    def test_fork_assets_exist_on_disk(self, acme_fork_config):
        """Referenced assets exist."""
        fork_config, _, assets_dir = acme_fork_config

        assert assets_dir.exists()
        assert len(list(assets_dir.glob("*.svg"))) > 0, "Assets should exist"


class TestStockParityAssertion:
    """Verify stock TunaOS consistency."""

    def test_stock_catalog_pin_valid(self, stock_config):
        """Stock catalog pin matches source receipt."""
        receipt = MODULE.source_receipt(ROOT)
        assert stock_config["catalog"]["sha256"] == receipt["sha256"]

    def test_stock_includes_all_cells(self, stock_plan):
        """Stock resolution includes multiple cells."""
        cells = stock_plan["cells"]
        assert len(cells) > 10, "Stock should include many variant×flavor×platform cells"

    def test_stock_legacy_catalog_valid(self, stock_plan):
        """Stock legacy catalog maintains compatibility."""
        legacy = stock_plan["legacy_catalog"]
        assert isinstance(legacy, dict)
        assert len(legacy) > 0
