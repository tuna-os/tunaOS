"""Primary TOML owns the matrix; generated adapters must never hide bad input."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/primary-config"
SPEC = importlib.util.spec_from_file_location("primary_config_under_test", ROOT / "scripts/lib/tunaos_config.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)


@pytest.fixture
def source_root(tmp_path):
    (tmp_path / "tunaos.toml").write_bytes((ROOT / "tunaos.toml").read_bytes())
    return tmp_path


def cli(root, command):
    return subprocess.run([sys.executable, str(ROOT / "scripts/config.py"), command,
                           "--root", str(root)], text=True, capture_output=True, cwd=root)


def node(document, path):
    for part in path:
        document = document[part]
    return document


def test_historical_migration_preserves_every_value_and_order():
    expected = json.loads((FIXTURES / "matrix-before-migration.json").read_text())
    source = FIXTURES / "matrix-source-at-4e03a122.toml"
    actual = config.matrix(config.load(source))
    assert actual == expected
    # JSON object order, variant ordering, and nested list order are contractual.
    assert json.dumps(actual, ensure_ascii=False) == json.dumps(expected, ensure_ascii=False)


@pytest.mark.parametrize("path", [(), ("build",), ("variants", "bonito"),
    ("variants", "bonito", "flavors", 0), ("iso_groups", 0),
    ("sibling_images", 0), ("tuna_rollout", "bonito")])
def test_unknown_keys_are_rejected_at_every_schema_level(path):
    document = config.load()
    node(document, path)["unknown_future_option"] = True
    with pytest.raises(config.ConfigError, match="unknown keys"):
        config.validate(document)


@pytest.mark.parametrize("path,key,value", [
    ((), "schema_version", True), ((), "schema_version", 2),
    ((), "build", []), ((), "variants", []), ((), "variants", {}),
    ((), "iso_groups", {}), ((), "sibling_images", {}),
    (("build",), "global_platforms", "linux/arm64"),
    (("build",), "global_platforms", []),
    (("build",), "global_platforms", ["linux/mips64"]),
    (("variants", "bonito"), "experimental", 1),
    (("variants", "bonito"), "base_image", "bad\nreference"),
    (("variants", "bonito"), "aliases", ["BadAlias"]),
    (("variants", "bonito"), "flavors", []),
    (("variants", "bonito", "flavors", 0), "stage", True),
    (("variants", "bonito", "flavors", 0), "stage", 0),
    (("variants", "bonito", "flavors", 0), "stage", 5),
    (("variants", "bonito", "flavors", 0), "build_image", "true"),
    (("variants", "bonito", "flavors", 0), "build_iso", 1),
    (("variants", "bonito", "flavors", 0), "build_qcow2", None),
    (("variants", "bonito", "flavors", 0), "luks_e2e", 0),
    (("variants", "bonito", "flavors", 0), "platforms", [1]),
    (("variants", "bonito", "flavors", 0), "id", "bad flavor"),
    (("iso_groups", 0), "offline_flavors", []),
    (("sibling_images", 0), "desktops", False),
    (("tuna_rollout", "bonito"), "status", "maybe"),
])
def test_invalid_types_and_values_fail_closed(path, key, value):
    document = config.load()
    node(document, path)[key] = value
    with pytest.raises(config.ConfigError):
        config.matrix(document)


@pytest.mark.parametrize("path", [("build", "global_platforms"),
    ("variants", "bonito", "flavors"), ("iso_groups",), ("sibling_images",),
    ("iso_groups", 0, "flavors"), ("sibling_images", 0, "desktops")])
def test_duplicate_entries_rejected(path):
    document = config.load()
    values = node(document, path)
    values.append(copy.deepcopy(values[0]))
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.validate(document)


@pytest.mark.parametrize("addition", ['\nschema_version = 1\nschema_version = 1\n',
    '\n[variants.bonito]\nbase_image = "duplicate"\n'])
def test_duplicate_toml_keys_or_tables_rejected(source_root, addition):
    source = source_root / "tunaos.toml"
    source.write_text(source.read_text() + addition)
    with pytest.raises(config.ConfigError):
        config.load(source)


def test_missing_required_field_and_rollout_mismatch_rejected():
    document = config.load()
    del document["variants"]["bonito"]["base_image"]
    with pytest.raises(config.ConfigError, match="missing keys"):
        config.validate(document)
    document = config.load()
    del document["tuna_rollout"]["bonito"]
    with pytest.raises(config.ConfigError, match="exactly all variants"):
        config.validate(document)


def test_prepare_refreshes_mutated_source_and_acceptance_cell(source_root):
    target = config.prepare(source_root)
    initial = target.read_bytes()
    source = source_root / "tunaos.toml"
    source.write_text(source.read_text() + "\n" + (FIXTURES / "bonito-gnome-x13s.toml").read_text() +
                      '\n[flavor_metadata.gnome-x13s]\ndesktop = "gnome"\nedition = "x13s"\n')
    assert config.prepare(source_root) == target
    assert target.read_bytes() != initial
    projected = json.loads(target.read_text())
    bonito = next(v for v in projected["variants"] if v["id"] == "bonito")
    assert bonito["flavors"][-1] == {
        "id": "gnome-x13s", "stage": 3, "platforms": ["linux/arm64"],
        "build_image": True, "build_iso": False, "build_qcow2": False, "luks_e2e": False}
    assert all(f["id"] != "gnome-x13s" for f in config.load()["variants"]["bonito"]["flavors"])


def test_invalid_source_never_replaces_existing_adapter(source_root):
    target = config.prepare(source_root)
    old_bytes, old_stat = target.read_bytes(), target.stat()
    (source_root / "tunaos.toml").write_text('schema_version = "invalid"\n')
    with pytest.raises(config.ConfigError):
        config.prepare(source_root)
    result = cli(source_root, "generate")
    assert result.returncode == 1 and "ERROR:" in result.stderr
    assert target.read_bytes() == old_bytes
    assert target.stat().st_mtime_ns == old_stat.st_mtime_ns
    assert not list(target.parent.glob(".build-config-*"))


def test_missing_source_cannot_fall_back_to_existing_adapter(source_root):
    target = config.prepare(source_root)
    (source_root / "tunaos.toml").unlink()
    assert target.exists()
    with pytest.raises(config.ConfigError):
        config.prepare(source_root)
    assert cli(source_root, "generate").returncode == 1


def test_generation_is_deterministic_and_does_not_rewrite_identical_bytes(source_root):
    target = config.prepare(source_root)
    before = target.stat()
    expected = config.render(config.load(source_root / "tunaos.toml")).encode()
    assert target.read_bytes() == expected
    assert config.prepare(source_root) == target
    assert target.stat().st_ino == before.st_ino
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    assert target.stat().st_mode & 0o777 == 0o644
    assert not list(target.parent.glob(".build-config-*"))


@pytest.mark.parametrize("symlink_parent", [False, True])
def test_generation_refuses_target_or_parent_symlinks(source_root, tmp_path, symlink_parent):
    external = tmp_path / "external"
    external.mkdir()
    victim = external / "build-config.yml"
    victim.write_text("do not touch")
    if symlink_parent:
        (source_root / ".github").symlink_to(external, target_is_directory=True)
    else:
        (source_root / ".github").mkdir()
        (source_root / ".github/build-config.yml").symlink_to(victim)
    with pytest.raises(config.ConfigError, match="symlink"):
        config.prepare(source_root)
    assert victim.read_text() == "do not touch"


def test_generation_refuses_directory_target(source_root):
    (source_root / ".github/build-config.yml").mkdir(parents=True)
    with pytest.raises(config.ConfigError, match="regular file"):
        config.prepare(source_root)


def test_cli_validate_show_generate(source_root):
    target = source_root / ".github/build-config.yml"
    result = cli(source_root, "validate")
    assert result.returncode == 0, result.stderr
    assert not target.exists()
    shown = cli(source_root, "show")
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout) == config.matrix(config.load())
    assert not target.exists()
    generated = cli(source_root, "generate")
    assert generated.returncode == 0, generated.stderr
    assert generated.stdout.strip() == str(target)
    assert target.read_text() == shown.stdout


def test_projection_does_not_mutate_source():
    document = config.load()
    projected = config.matrix(document)
    projected["variants"][0]["flavors"].clear()
    assert document["variants"][next(iter(document["variants"]))]["flavors"]


def test_missing_both_toml_parsers_explains_dependency():
    code = '''import builtins, runpy, sys
original = builtins.__import__
def blocked(name, *args, **kwargs):
    if name in ("tomllib", "tomli"):
        raise ModuleNotFoundError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
runpy.run_path(sys.argv[1])
'''
    result = subprocess.run([sys.executable, "-c", code, str(ROOT / "scripts/lib/tunaos_config.py")],
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "requirements-config.txt" in result.stderr


def test_tomli_fallback_is_selected_when_stdlib_parser_is_missing():
    # Use the standard parser behind a test-only tomli shim to exercise the
    # import fallback without adding a dependency to >=3.11 test environments.
    code = '''import builtins, runpy, sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
sys.modules["tomli"] = tomllib
original = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == "tomllib":
        raise ModuleNotFoundError(name)
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
module = runpy.run_path(sys.argv[1])
assert module["load"]()["schema_version"] == 1
'''
    result = subprocess.run([sys.executable, "-c", code, str(ROOT / "scripts/lib/tunaos_config.py")],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_failed_atomic_replace_keeps_previous_adapter_and_removes_temp(source_root, monkeypatch):
    target = config.prepare(source_root)
    old_bytes = target.read_bytes()
    source = source_root / "tunaos.toml"
    source.write_text(source.read_text() + "\n" + (FIXTURES / "bonito-gnome-x13s.toml").read_text() +
                      '\n[flavor_metadata.gnome-x13s]\ndesktop = "gnome"\nedition = "x13s"\n')

    def refuse_replace(self, destination):
        raise OSError("injected atomic replacement failure")

    monkeypatch.setattr(Path, "replace", refuse_replace)
    with pytest.raises(OSError, match="injected"):
        config.prepare(source_root)
    assert target.read_bytes() == old_bytes
    assert not list(target.parent.glob(".build-config-*"))


def test_unsupported_rollout_requires_reason():
    document = config.load()
    document["tuna_rollout"]["bonito"] = {"status": "unsupported", "package_target": "bonito"}
    with pytest.raises(config.ConfigError, match="reason"):
        config.validate(document)


def test_renovate_updates_only_primary_source_and_adapter_follows(tmp_path):
    import re
    settings = json.loads((ROOT / "renovate.json").read_text())
    managers = [manager for manager in settings["customManagers"]
                if manager.get("managerFilePatterns") == [r"/^tunaos\.toml$/"]]
    assert len(managers) == 1
    pattern = re.sub(r"\(\?<([^>]+)>", r"(?P<\1>", managers[0]["matchStrings"][0])
    source = (ROOT / "tunaos.toml").read_text()
    matches = list(re.finditer(pattern, source))
    pinned = [v for v in config.load()["variants"].values() if "@sha256:" in v["base_image"]]
    assert len(matches) == len(pinned)
    original = matches[0].group("currentDigest")
    updated = source.replace(original, "sha256:" + "a" * 64, 1)
    (tmp_path / "tunaos.toml").write_text(updated)
    adapter = config.prepare(tmp_path)
    first = next(iter(config.load()["variants"]))
    assert json.loads(adapter.read_text())["variants"][0]["base_image"] == (
        config.load()["variants"][first]["base_image"].replace(original, "sha256:" + "a" * 64))
    assert not any("build-config" in pattern for manager in settings["customManagers"]
                   for pattern in manager.get("managerFilePatterns", []))


def test_shell_reader_prepares_absent_adapter_in_fresh_checkout(tmp_path):
    import shutil
    for name in ("tunaos.toml", "scripts/config.py", "scripts/lib/tunaos_config.py",
                 "scripts/lib/tunaos_packages.py", "scripts/lib/desktop_operations.json",
                 "scripts/lib/iso_builder_config.py",
                 "scripts/lib/build-config.sh"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    result = subprocess.run(["bash", "-c", 'source "$1"; tunaos_build_config', "bash",
                             str(tmp_path / "scripts/lib/build-config.sh")],
                            text=True, capture_output=True, check=True)
    assert Path(result.stdout.strip()) == tmp_path / ".github/build-config.yml"
    assert json.loads(Path(result.stdout.strip()).read_text()) == config.matrix(config.load())


@pytest.mark.parametrize("resolver", ["echo invalid-config >&2; exit 1", "exit 0"])
def test_install_does_not_guess_an_image_when_resolution_fails(tmp_path, resolver):
    script = (ROOT / "scripts/iso-e2e.sh").read_text()
    block = script.split('\tlocal published_ref=""', 1)[1].split('\n\tlocal target_imgref=', 1)[0]
    helper = tmp_path / "published-image-ref.sh"
    helper.write_text("#!/bin/sh\n" + resolver + "\n")
    helper.chmod(0o755)
    harness = ('resolve() {\nlocal published_ref=""' + block +
               '\nprintf "WRONG-CONTINUATION:%s\\n" "$published_ref"\n}\nresolve\n')
    result = subprocess.run(["bash", "-c", harness], text=True, capture_output=True,
                            env={**__import__('os').environ, "SCRIPT_DIR": str(tmp_path),
                                 "VARIANT": "flounder-sid", "FLAVOR": "gnome"})
    assert result.returncode != 0
    assert "WRONG-CONTINUATION" not in result.stdout
    assert "cannot resolve the published image" in result.stderr
    if "invalid-config" in resolver:
        assert "invalid-config" in result.stderr


@pytest.mark.parametrize("toml11", ['value = {\n key = 1,\n}\n', 'value = "\\x41"\n'])
def test_parser_keeps_the_shared_toml10_grammar(toml11):
    # 3.10 and 3.11 must reject edits only newer TOML parsers understand.
    with pytest.raises(config.tomllib.TOMLDecodeError):
        config.tomllib.loads(toml11)


def test_tomli_dependency_ceiling_preserves_shared_toml_grammar():
    settings = json.loads((ROOT / "renovate.json").read_text())
    rules = [
        rule for rule in settings["packageRules"]
        if "tomli" in rule.get("matchPackageNames", [])
    ]
    assert len(rules) == 1
    assert rules[0]["allowedVersions"] == "<2.5.0"


@pytest.mark.parametrize("recipe", ["check:", "_ensure_test_deps:", "clean:"])
def test_just_config_preparation_stops_before_consumers(recipe):
    body = (ROOT / "just/utilities.just").read_text().split(recipe, 1)[1]
    line = next(line.strip() for line in body.splitlines() if "scripts/config.py" in line)
    assert '{{ justfile_directory() }}/scripts/config.py' in line
    # Use a failing generator, without running later lint, install, or clean steps.
    command = line.replace('python3 "{{ justfile_directory() }}/scripts/config.py" generate', 'false')
    result = subprocess.run(["bash", "-c", command + '\necho WRONG-CONTINUATION'],
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "WRONG-CONTINUATION" not in result.stdout


@pytest.mark.parametrize("reserved", ["bonito", "custom-published"])
def test_alias_cannot_shadow_canonical_image_name(reserved):
    document = config.load()
    document["variants"]["yellowfin"]["publish_name"] = "custom-published"
    document["variants"]["bonito"]["aliases"] = [reserved]
    with pytest.raises(config.ConfigError, match="shadows a canonical image"):
        config.validate(document)


def test_alias_collision_is_checked_using_complete_published_tag():
    document = config.load()
    document["variants"]["bonito-rawhide"]["publish_name"] = "fedora-development"
    document["variants"]["bonito-rawhide"]["tag_suffix"] = ""
    with pytest.raises(config.ConfigError, match="expected single-line string"):
        config.validate(document)
    del document["variants"]["bonito-rawhide"]["tag_suffix"]
    with pytest.raises(config.ConfigError, match="fedora:base also belongs to bonito"):
        config.validate(document)


def test_shared_aliases_keep_distinct_stock_tag_suffixes():
    variants = config.load()["variants"]
    for stable, rolling, alias, suffix in (("bonito", "bonito-rawhide", "fedora", "rawhide"),
                                           ("flounder", "flounder-sid", "debian", "sid")):
        assert alias in variants[stable]["aliases"]
        assert alias in variants[rolling]["aliases"]
        assert variants[stable].get("tag_suffix", "") == ""
        assert variants[rolling]["tag_suffix"] == suffix


@pytest.mark.parametrize("key", ["flavors", "offline_flavors"])
def test_unknown_iso_flavor_is_rejected(key):
    document = config.load()
    document["iso_groups"][0][key].append("unknown-desktop")
    with pytest.raises(config.ConfigError, match=f"{key}: unknown flavors"):
        config.validate(document)


@pytest.mark.parametrize("variant,flavor,platform", [
    ("skipjack", "gnome", "linux/amd64/v2"), ("sailfin", "gnome", "linux/arm64"),
    ("marlin", "gnome", "linux/arm64"), ("flounder", "gnome", "linux/arm64")])
def test_flavor_platforms_can_extend_variant_defaults(variant, flavor, platform):
    entry = config.load()["variants"][variant]
    assert platform not in entry["platforms"]
    assert platform in next(f for f in entry["flavors"] if f["id"] == flavor)["platforms"]


def test_offline_iso_payload_can_include_non_live_flavors():
    groups = config.load()["iso_groups"]
    gnome = next(group for group in groups if group["suffix"] == "")
    assert "gnome" not in gnome["flavors"]
    assert "gnome" in gnome["offline_flavors"]


def test_canonical_publication_collision_is_rejected():
    document = config.load()
    document["variants"]["yellowfin"]["publish_name"] = "albacore"
    with pytest.raises(config.ConfigError, match="albacore:base also belongs to yellowfin"):
        config.validate(document)


def test_canonical_names_can_be_shared_when_complete_tags_differ():
    document = config.load()
    document["variants"]["yellowfin"]["publish_name"] = "albacore"
    document["variants"]["yellowfin"]["tag_suffix"] = "kitten"
    config.validate(document)


def test_renovate_only_pin_update_keeps_live_suite_green(tmp_path):
    import hashlib
    import shutil
    checkout = tmp_path / "checkout"
    for name in ("tunaos.toml", "renovate.json", "requirements-config.txt",
                 "scripts/config.py", "scripts/lib/tunaos_config.py",
                 "scripts/lib/tunaos_packages.py", "scripts/lib/desktop_operations.json",
                 "scripts/lib/iso_builder_config.py",
                 "scripts/lib/build-config.sh", "scripts/iso-e2e.sh",
                 "just/utilities.just", ".github/workflows/reusable-build-image.yml",
                 "tests/test_primary_config.py"):
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    fixtures = checkout / "tests/fixtures/primary-config"
    shutil.copytree(FIXTURES, fixtures)
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixtures.iterdir()}
    primary = checkout / "tunaos.toml"
    source = primary.read_text()
    variant_id, old = next((name, v["base_image"]) for name, v in config.load()["variants"].items()
                           if "@sha256:" in v["base_image"])
    replacement = old.split("@sha256:")[0] + "@sha256:" + "b" * 64
    primary.write_text(source.replace(old, replacement, 1))
    # Run every core case except this recursive orchestration test. The child
    # uses the changed live pin but the original historical fixtures.
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             "tests/test_primary_config.py", "-k",
                             "not renovate_only_pin_update_keeps_live_suite_green"],
                            cwd=checkout, text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixtures.iterdir()} == before
    emitted = config.matrix(config.load(primary))
    assert next(v for v in emitted["variants"] if v["id"] == variant_id)["base_image"] == replacement


@pytest.mark.parametrize("suffix", ["amd64", "arm64", "linux-amd64", "testing", "20261020", "amd64-20261020"])
def test_generated_publication_tag_collisions_are_rejected(suffix):
    document = config.load()
    document["variants"]["bonito-rawhide"]["tag_suffix"] = suffix
    with pytest.raises(config.ConfigError, match="also belongs to bonito"):
        config.validate(document)


def test_architecture_override_publication_collision_is_rejected():
    document = config.load()
    document["variants"]["yellowfin"]["publish_name"] = "skipjack"
    document["variants"]["yellowfin"]["tag_suffix"] = "amd64-v2"
    with pytest.raises(config.ConfigError, match="also belongs to"):
        config.validate(document)


@pytest.mark.parametrize("left,dated,right,other_dated,expected", [
    ("gnome", True, "gnome-20261020", False, True),
    ("gnome-20261020", False, "gnome", True, True),
    ("gnome", True, "gnome", True, True),
    ("gnome", True, "gnome-20261340", False, False),
    ("gnome", True, "gnome-2026102", False, False),
    ("gnome", True, "gnome-testing", False, False),
    ("gnome", True, "gnome-amd64", True, False),
])
def test_publication_date_families(left, dated, right, other_dated, expected):
    assert config.publication_tags_overlap(left, dated, right, other_dated) is expected


def test_generated_tag_collision_between_flavors_is_rejected():
    document = config.load()
    variant = document["variants"]["bonito"]
    extra = copy.deepcopy(next(f for f in variant["flavors"] if f["id"] == "gnome"))
    extra["id"] = "gnome-testing"
    variant["flavors"].append(extra)
    with pytest.raises(config.ConfigError, match="also belongs to bonito"):
        config.validate(document)


def test_publication_validator_tracks_workflow_tag_producers():
    import re
    workflow = (ROOT / ".github/workflows/reusable-build-image.yml").read_text()
    # A producer change must update the namespace model and collision fixtures.
    copies = set(re.findall(r'^\s+copy_retry "([^"\n]+)"', workflow, re.MULTILINE))
    canonical = "${IMAGE_REGISTRY}/${IMAGE_NAME}:${DEFAULT_TAG}"
    alias = "${IMAGE_REGISTRY}/${alias_name}:${DEFAULT_TAG}"
    assert copies == {canonical, canonical + "-${DATE_TAG}", canonical + "-${arch}",
                      canonical + "-${arch}-${DATE_TAG}", alias, alias + "-${DATE_TAG}"}
    assert 'DATE_TAG="$(date +%Y%m%d)"' in workflow
    assert 'arch="${platform#linux/}"' in workflow
    assert 'arch="${arch//\\//-}"' in workflow
    assert 'type=raw,value=${{ env.DEFAULT_TAG}}' in workflow
    assert '$IMAGE_REGISTRY/$IMAGE_NAME:${tag}-testing' in workflow
    assert canonical + '-${SAFE_PLATFORM}"' in workflow
    assert canonical + '-${SAFE_PLATFORM}.packages"' in workflow
