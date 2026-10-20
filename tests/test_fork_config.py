"""Phase 1 compiles review intent; stock adapter keeps the build contract intact."""
import copy
import fnmatch
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fork_config", ROOT / "scripts/resolve-fork-config.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture(scope="module")
def stock():
    template = yaml.safe_load((ROOT / "examples/fork/stock.template.yaml").read_text())
    return {**template, "catalog": {"sha256": MODULE.source_receipt(ROOT)["sha256"]}}


@pytest.fixture(scope="module")
def plan(stock):
    return MODULE.resolve(stock, ROOT)


def test_stock_catalog_preserves_every_key_and_safety_hold(plan):
    original = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
    assert plan["legacy_catalog"] == original
    assert plan["mode"] == "review-only"
    assert plan["consumers_integrated"] is False
    expected = []
    for variant in original["variants"]:
        for flavor in variant["flavors"]:
            for platform in flavor.get("platforms", variant["platforms"]):
                expected.append((variant["id"], flavor["id"], platform, flavor.get("build_image", False)))
    assert [(c["variant"], c["flavor"], c["platform"], c["build_image"]) for c in plan["cells"]] == expected
    assert any(not c["build_image"] for c in plan["cells"])
    assert all(c["selected"] for c in plan["cells"])
    for variant, rollout in original["tuna_rollout"].items():
        if rollout["status"] == "unsupported":
            assert not any(c["variant"] == variant and c["flavor"] == "tuna" and c["build_image"] for c in plan["cells"])


def test_every_routing_result_matches_existing_resolver(plan):
    pairs = {(c["variant"], c["flavor"]): c["routing"] for c in plan["cells"]}
    for (variant, flavor), actual in pairs.items():
        output = subprocess.check_output(["bash", str(ROOT / "scripts/resolve-flavor.sh"), variant, flavor], text=True)
        expected = {k: json.loads(v) for k, v in (line.split("=", 1) for line in output.splitlines())}
        assert actual == expected


def test_source_receipt_preserves_package_and_identity_inputs(plan):
    files = plan["sources"]["files"]
    for path in ROOT.glob("manifests/desktops/*.yaml"):
        assert files[path.relative_to(ROOT).as_posix()] == hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("build_scripts/10-base-packages.sh", "build_scripts/20-packages.sh",
                 "build_scripts/90-image-info.sh", "build_scripts/lib/variant-identity.tsv",
                 "build_scripts/desktop/install-desktop.sh", "build_scripts/desktop/configure-desktop-runtime.sh"):
        assert files[name] == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    assert "not an effective package transaction" in plan["package_resolution"]


def test_stock_adapter_and_build_config_seam(tmp_path, stock):
    config = tmp_path / "stock.yaml"
    config.write_text(yaml.safe_dump(stock))
    output = subprocess.check_output(["python3", str(ROOT / "scripts/resolve-fork-config.py"),
                                      str(config), "--format", "legacy"], text=True)
    adapted = tmp_path / "build.json"
    adapted.write_text(output)
    original = yaml.safe_load((ROOT / ".github/build-config.yml").read_text())
    assert json.loads(output) == original
    env = dict(os.environ, TUNAOS_BUILD_CONFIG=str(adapted))
    for variant in original["variants"]:
        actual = subprocess.check_output(["bash", "scripts/resolve-image.sh", variant["id"], "base"],
                                         cwd=ROOT, env=env, text=True).strip()
        assert actual == variant["base_image"]


@pytest.mark.parametrize("update", [
    {"extra": 1}, {"schema_version": True}, {"schema_version": "1"},
    {"catalog": {"sha256": "main"}}, {"image": {"registry": "ghcr.io"}},
    {"targets": {"variants": "yellowfin"}}, {"targets": {"flavors": []}},
    {"targets": {"variants": ["invented"]}}, {"targets": {"platforms": ["linux/amd64", "linux/amd64"]}},
    {"global": {"branding": {"unknown": "x"}}}, {"global": {"branding": {"name": False}}},
    {"global": {"branding": {"homepage": "http://example.com"}}},
    {"global": {"packages": {"add": "vim"}}}, {"global": {"packages": {"add": [True]}}},
    {"global": {"packages": {"repositories": [{"id": "repo", "url": "https://example.com"}]}}},
    {"overrides": {"cells": {"hummingbird:tuna": {}}}},
    {"overrides": {"variants": {"invented": {}}}},
    {"global": {"packages": {"add": ["vim"], "remove": ["vim"]}}},
])
def test_strict_validation(stock, update):
    config = {**stock, **update}
    with pytest.raises(MODULE.ConfigError):
        MODULE.resolve(config, ROOT)


@pytest.mark.parametrize("body", ["schema_version: 1\nschema_version: 1\n", "global:\n  branding:\n    name: A\n    name: B\n", "1: bad\n"])
def test_duplicate_and_nonstring_yaml_keys_rejected(body):
    with pytest.raises(MODULE.ConfigError):
        yaml.load(body, Loader=MODULE.UniqueLoader)


def test_catalog_pin_fails_closed(stock):
    with pytest.raises(MODULE.ConfigError, match="pin mismatch"):
        MODULE.resolve({**stock, "catalog": {"sha256": "0" * 64}}, ROOT)


def test_precedence_and_stable_dedup(stock):
    config = copy.deepcopy(stock)
    config.update({"global": {"branding": {"name": "Global"}, "packages": {"add": ["one", "two"]}},
                   "overrides": {
                       "variants": {"yellowfin": {"branding": {"name": "Variant"}, "packages": {"add": ["two", "three"]}}},
                       "desktops": {"gnome": {"branding": {"name": "Desktop"}}},
                       "cells": {"yellowfin:gnome": {"branding": {"name": "Cell"}, "packages": {"add": ["four"]}}}}})
    result = MODULE.resolve(config, ROOT)
    cell = next(c for c in result["cells"] if c["variant"] == "yellowfin" and c["flavor"] == "gnome")
    assert cell["intent"]["branding"]["name"] == "Cell"
    assert cell["intent"]["packages"]["add"] == ["one", "two", "three", "four"]
    other = next(c for c in result["cells"] if c["variant"] == "yellowfin" and c["flavor"] == "gnome-hwe")
    assert other["intent"]["branding"]["name"] == "Desktop"


def test_cross_scope_conflict_rejected(stock):
    config = {**stock, "global": {"packages": {"add": ["vim"]}},
              "overrides": {"variants": {"yellowfin": {"packages": {"remove": ["vim"]}}}}}
    with pytest.raises(MODULE.ConfigError, match="conflicting"):
        MODULE.resolve(config, ROOT)


def test_selection_never_enables_a_hold(stock):
    config = {**stock, "targets": {"variants": ["yellowfin"], "flavors": ["gnome", "gnome-asahi"]}}
    result = MODULE.resolve(config, ROOT)
    held = [c for c in result["cells"] if c["variant"] == "yellowfin" and c["flavor"] == "gnome-asahi"]
    assert held and all(c["selected"] and not c["build_image"] for c in held)
    assert result["legacy_catalog"] == yaml.safe_load((ROOT / ".github/build-config.yml").read_text())


def test_asset_paths_and_symlink_escape(stock, tmp_path):
    (tmp_path / "logo.svg").write_text("<svg/>")
    config = {**stock, "global": {"branding": {"logo": "logo.svg"}}}
    MODULE.resolve(config, tmp_path)
    for name in ("../outside.svg", "/tmp/abs.svg", "missing.svg"):
        config["global"]["branding"]["logo"] = name
        with pytest.raises(MODULE.ConfigError, match="config-relative"):
            MODULE.resolve(config, tmp_path)
    (tmp_path / "escape").symlink_to(ROOT / "AGENTS.md")
    config["global"]["branding"]["logo"] = "escape"
    with pytest.raises(MODULE.ConfigError, match="config-relative"):
        MODULE.resolve(config, tmp_path)


def test_environment_catalog_mismatch_rejected(stock, monkeypatch, tmp_path):
    custom = tmp_path / "other.yaml"
    custom.write_text("variants: []\n")
    monkeypatch.setenv("TUNAOS_BUILD_CONFIG", str(custom))
    with pytest.raises(MODULE.ConfigError, match="differs"):
        MODULE.resolve(stock, ROOT)


@pytest.mark.parametrize("extra", [{"targets": {"variants": ["yellowfin"]}}, {"global": {"branding": {"name": "Fork"}}}])
def test_adapter_refuses_unimplemented_fork_application(stock, tmp_path, extra):
    path = tmp_path / "fork.yaml"
    path.write_text(yaml.safe_dump({**stock, **extra}))
    result = subprocess.run(["python3", str(ROOT / "scripts/resolve-fork-config.py"), str(path), "--format", "legacy"], capture_output=True, text=True)
    assert result.returncode == 2
    assert not result.stdout
    assert "stock intent only" in result.stderr


def test_plan_enabled_cells_match_the_real_workflow_query(plan):
    """Execute the workflow's matrix expression, not a copied approximation."""
    workflow = (ROOT / ".github/workflows/build-variant.yml").read_text()
    query = workflow.split("--arg event \"${EVENT_NAME}\" '", 1)[1].split("' | jq -c -s '.'", 1)[0]
    result = subprocess.run(["jq", "-c", "--arg", "event", "workflow_dispatch", query],
                            input=json.dumps(plan["legacy_catalog"]), text=True, capture_output=True,
                            env=dict(os.environ, FILTER_VARIANT="all", FILTER_FLAVOR="all"), check=True)
    actual = {(row["variant"], row["flavor"], platform) for row in map(json.loads, result.stdout.splitlines())
              for platform in row["platforms"].split(",")}
    expected = {(c["variant"], c["flavor"], c["platform"]) for c in plan["cells"] if c["build_image"]}
    assert actual == expected


def test_read_only_plan_is_deterministic(stock):
    assert MODULE.resolve(stock, ROOT) == MODULE.resolve(stock, ROOT)


def test_symlink_receipt_hashes_target_without_following_it(plan):
    name = "system_files/etc/systemd/system/auditd.service"
    path = ROOT / name
    assert path.is_symlink()
    assert plan["sources"]["files"][name] == hashlib.sha256(b"symlink:" + os.readlink(path).encode()).hexdigest()


@pytest.mark.parametrize("registry,namespace", [("ghcr.io/path", "fork"), ("host:99999", "fork"), ("ghcr.io", "../fork")])
def test_invalid_image_coordinates(stock, registry, namespace):
    with pytest.raises(MODULE.ConfigError):
        MODULE.resolve({**stock, "image": {"registry": registry, "namespace": namespace}}, ROOT)


def test_repository_conflicts_and_operation_order():
    repo = {"id": "example", "url": "https://example.org/repo", "key_url": "https://example.org/key"}
    layer = {"packages": {"repositories": [repo], "add": ["vim"]}}
    merged = MODULE.merge_layers([layer, layer, {"packages": {"add": []}}])
    assert merged["packages"]["repositories"] == [repo]
    assert merged["packages"]["add"] == ["vim"]
    assert list(merged["packages"]) == ["repositories", "remove", "add", "optional"]
    other = {"packages": {"repositories": [{**repo, "url": "https://different.org/repo"}]}}
    with pytest.raises(MODULE.ConfigError, match="conflicting inherited"):
        MODULE.merge_layers([layer, other])


def test_stock_example_edits_trigger_the_contract_suite():
    workflow = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())
    assert "examples/**" in workflow[True]["pull_request"]["paths"]


def test_receipt_ignores_generated_untracked_files_but_detects_source_changes(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "system_files/usr/libexec/probe.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("print('stock')\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    before = MODULE.source_receipt(tmp_path)
    cache = source.parent / "__pycache__/probe.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"generated runtime bytes")
    assert MODULE.source_receipt(tmp_path) == before
    source.write_text("print('changed')\n")
    assert MODULE.source_receipt(tmp_path)["sha256"] != before["sha256"]


@pytest.mark.parametrize("name", [
    "system_files_overrides/marlin/usr/lib/bootc/install/50-marlin.toml",
    "experiences/tuna/files/etc/greetd/environments",
    "build_scripts/bootc/sandbox/usr/lib/ostree/prepare-root.conf",
    "build_scripts/checks/package-miss-allowlist.txt",
    "scripts/_registry.sh",
    "scripts/build-image-inner.sh",
    "Justfile",
    "just/build.just",
    "custom/etc/example.conf",
    ".containerignore",
    ".dockerignore",
])
def test_consumed_payload_mutation_invalidates_the_old_pin(tmp_path, name):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("stock payload\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    before = MODULE.source_receipt(tmp_path)
    assert name in before["files"]
    config = {"schema_version": 1, "catalog": {"sha256": before["sha256"]}}
    source.write_text("changed payload\n")
    assert MODULE.source_receipt(tmp_path)["sha256"] != before["sha256"]
    with pytest.raises(MODULE.ConfigError, match="pin mismatch"):
        MODULE.resolve(config, tmp_path, root=tmp_path)


def test_every_receipt_input_triggers_the_contract_suite(plan):
    workflow = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())
    patterns = workflow[True]["pull_request"]["paths"]
    missing = [name for name in plan["sources"]["files"]
               if not any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)]
    assert not missing


def test_receipt_detects_executable_mode_changes(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "build_scripts/probe.sh"
    source.parent.mkdir()
    source.write_text("#!/bin/sh\n")
    source.chmod(0o644)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    before = MODULE.source_receipt(tmp_path)
    source.chmod(0o755)
    after = MODULE.source_receipt(tmp_path)
    assert before["files"] == after["files"]
    assert before["modes"]["build_scripts/probe.sh"] == "100644"
    assert after["modes"]["build_scripts/probe.sh"] == "100755"
    assert before["sha256"] != after["sha256"]
    config = {"schema_version": 1, "catalog": {"sha256": before["sha256"]}}
    with pytest.raises(MODULE.ConfigError, match="pin mismatch"):
        MODULE.resolve(config, tmp_path, root=tmp_path)


def test_receipt_detects_symlink_target_changes_and_source_deletion(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "system_files/probe"
    source.parent.mkdir()
    source.symlink_to("/missing-first")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    before = MODULE.source_receipt(tmp_path)
    source.unlink()
    source.symlink_to("/missing-second")
    after = MODULE.source_receipt(tmp_path)
    assert after["modes"]["system_files/probe"] == "120000"
    assert before["sha256"] != after["sha256"]
    source.unlink()
    assert MODULE.source_receipt(tmp_path)["sha256"] != after["sha256"]


def test_explain_keeps_default_plan_unchanged(stock):
    plain = MODULE.resolve(stock, ROOT)
    explained = MODULE.resolve(stock, ROOT, explain=True)
    assert 'explanation' not in plain
    assert explained.pop('explanation')['scope'] == 'config-delta-intent-only'
    for cell in explained['cells']:
        assert cell.pop('intent_provenance') == {
            'branding': {}, 'packages': {'repositories': [], 'remove': [], 'add': [], 'optional': []}}
    assert explained == plain


def test_explain_effective_brand_and_all_list_origins(stock):
    config = copy.deepcopy(stock)
    config.update({
        'image': {'registry': 'ghcr.io', 'namespace': 'example'},
        'targets': {'variants': ['yellowfin'], 'flavors': ['gnome']},
        'global': {'branding': {'name': 'Global'}, 'packages': {'add': ['vim'], 'remove': ['old']}},
        'overrides': {
            'variants': {'yellowfin': {'branding': {'name': 'Variant'}, 'packages': {'add': ['vim', 'git']}}},
            'desktops': {'gnome': {'branding': {'name': 'Desktop'}, 'packages': {'optional': ['htop']}}},
            'cells': {'yellowfin:gnome': {'branding': {'name': 'Cell'}, 'packages': {'add': []}}},
        },
    })
    plan = MODULE.resolve(config, ROOT, explain=True)
    cell = next(c for c in plan['cells'] if c['selected'])
    assert cell['intent']['branding']['name'] == 'Cell'
    assert cell['intent_provenance']['branding']['name'] == {
        'effective_source': 'overrides.cells.yellowfin:gnome.branding.name',
        'sources': ['global.branding.name', 'overrides.variants.yellowfin.branding.name',
                    'overrides.desktops.gnome.branding.name', 'overrides.cells.yellowfin:gnome.branding.name']}
    assert cell['intent_provenance']['packages']['add'] == [
        {'index': 0, 'sources': ['global.packages.add[0]', 'overrides.variants.yellowfin.packages.add[0]']},
        {'index': 1, 'sources': ['overrides.variants.yellowfin.packages.add[1]']}]
    assert cell['intent_provenance']['packages']['remove'] == [{'index': 0, 'sources': ['global.packages.remove[0]']}]
    assert cell['intent_provenance']['packages']['optional'] == [{'index': 0, 'sources': ['overrides.desktops.gnome.packages.optional[0]']}]
    assert plan['explanation']['image_sources'] == {'namespace': 'image.namespace', 'registry': 'image.registry'}
    assert plan['explanation']['target_sources']['platforms'] == 'catalog:all-declared'
    # Origins contain keys and indices only, not shadowed values or private host paths.
    origins = json.dumps(cell['intent_provenance'])
    assert 'Global' not in origins and str(ROOT) not in origins
    assert MODULE.resolve(config, ROOT, explain=True) == plan


def test_explain_repositories_deduplicate_without_repeating_values():
    repo = {'id': 'example', 'url': 'https://example.org/repo', 'key_url': 'https://example.org/key'}
    layers = [('global', {'packages': {'repositories': [repo]}}),
              ('overrides.variants.yellowfin', {'packages': {'repositories': [repo]}})]
    intent = MODULE.merge_layers([layer for _, layer in layers])
    result = MODULE.explain_layers(layers, intent)
    assert result['packages']['repositories'] == [{'index': 0, 'sources': [
        'global.packages.repositories[0]', 'overrides.variants.yellowfin.packages.repositories[0]']}]
    assert 'https://' not in json.dumps(result)


def test_explain_still_rejects_cross_scope_conflicts(stock):
    config = {**stock, 'global': {'packages': {'add': ['vim']}},
              'overrides': {'desktops': {'gnome': {'packages': {'remove': ['vim']}}}}}
    with pytest.raises(MODULE.ConfigError, match='conflicting package operations'):
        MODULE.resolve(config, ROOT, explain=True)


@pytest.mark.parametrize('extra', [['--catalog-pin'], ['--format', 'legacy']])
def test_explain_rejects_incompatible_cli_modes(extra):
    result = subprocess.run(['python3', str(ROOT / 'scripts/resolve-fork-config.py'), '--explain', *extra],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert '--explain requires config and --format plan' in result.stderr


def test_template_initialization_rejects_explain_mode():
    result = subprocess.run(['python3', str(ROOT / 'scripts/resolve-fork-config.py'),
                             '--init-template', str(ROOT / 'examples/fork/stock.template.yaml'),
                             '--explain'], capture_output=True, text=True)
    assert result.returncode == 2
    assert '--init-template cannot be combined' in result.stderr
    assert not result.stdout
