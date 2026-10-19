"""Config-to-installer contracts; fixture trees are not native install evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fork_source", ROOT / "build_scripts/lib/fork-installer-source.py")
SOURCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE)


def manifest(platform="linux/amd64"):
    return {"schema_version": 1, "image": {"registry": "localhost", "namespace": "harbor"},
            "variant": "yellowfin", "flavor": "gnome", "platform": platform}


def prepare_root(context, root, value):
    """Real canonical backend probe, with an inspectable legacy EFI payload."""
    (context / "build_scripts/lib").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "build_scripts/lib/fork-installer-source.py", context / "build_scripts/lib/fork-installer-source.py")
    shutil.copyfile(ROOT / "live-iso/common/src/installer-recipe-backend.sh", context / SOURCE.PROBE)
    recipe = json.loads((ROOT / "system_files" / SOURCE.RECIPE).read_text())
    recipe, catalog = SOURCE.project(value, recipe)
    for relative, data in ((SOURCE.RECIPE, recipe), (SOURCE.CATALOG, catalog)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
    efi = root / "usr/lib/bootupd/updates/EFI/test/grubx64.efi"
    efi.parent.mkdir(parents=True, exist_ok=True)
    efi.write_bytes(b"fixture payload")


@pytest.mark.parametrize("platform,suffix", [("linux/amd64", "linux-amd64"), ("linux/amd64/v2", "linux-amd64-v2"), ("linux/arm64", "linux-arm64")])
def test_exact_cell_reference_has_no_stock_or_arch_fallback(platform, suffix):
    assert SOURCE.target_ref(manifest(platform)) == "localhost/harbor/yellowfin:gnome-" + suffix


@pytest.mark.parametrize("field,value", [("namespace", "../tuna-os"), ("registry", "ghcr.io/other"), ("registry", "host:0")])
def test_invalid_target_tokens_fail(field, value):
    m = manifest()
    m["image"][field] = value
    with pytest.raises(ValueError):
        SOURCE.target_ref(m)


def test_catalog_matches_inherited_reference_and_preserves_other_entries():
    old = "ghcr.io/tuna-os/yellowfin:gnome"
    other = {"name": "Other", "imgref": "example.org/team/os:latest", "filesystem": "ext4"}
    catalog = {"default_image": old, "fallback_flatpaks": ["org.example.App"], "images": [
        {"name": "Group", "registry": old.rsplit(":", 1)[0], "children": [
            {"name": "Old", "imgref": None, "tag": "gnome", "bootloader": "grub2"}, other]}]}
    before = copy.deepcopy(catalog)
    recipe, actual = SOURCE.project(manifest(), {"imgref": old, "steps": {"disk": {}}, "filesystem": "xfs"}, catalog)
    target = SOURCE.target_ref(manifest())
    assert recipe["imgref"] == target and recipe["local_imgref"] == "containers-storage:" + target
    assert recipe["steps"] == {"disk": {}} and recipe["filesystem"] == "xfs"
    assert actual["default_image"] == target
    assert actual["images"][0]["children"][1] == other
    assert actual["fallback_flatpaks"] == ["org.example.App"]
    assert catalog == before


@pytest.mark.parametrize("nodes", [[], [{"name": "other", "imgref": "other:tag"}],
                                     [{"imgref": "old:tag"}, {"imgref": "old:tag"}],
                                     [{"tag": "unresolved"}], [{"imgref": "old:tag", "children": []}]])
def test_missing_ambiguous_or_unresolvable_catalog_fails(nodes):
    with pytest.raises(ValueError):
        SOURCE.project(manifest(), {"imgref": "old:tag"}, {"images": nodes})


def test_recipe_catalog_default_is_routed_as_well():
    recipe = {"imgref": "old:tag", "images": [{"name": "Old", "imgref": "old:tag"},
                                                {"name": "Other", "imgref": "other:tag", "default": True}]}
    actual, catalog = SOURCE.project(manifest(), recipe)
    assert actual["images"][0]["default"] is True
    assert actual["images"][1]["default"] is False
    SOURCE.verify(manifest(), actual, catalog)


@pytest.mark.parametrize("sealed,bootupd", [(False, True), (True, True), (True, False), (False, False)])
def test_final_recipe_and_frontend_leaf_use_real_root_probe(tmp_path, sealed, bootupd):
    context, root = tmp_path / "context", tmp_path / "root"
    prepare_root(context, root, manifest())
    if not bootupd:
        (root / "usr/lib/bootupd/updates/EFI/test/grubx64.efi").unlink()
        efi = root / "usr/lib/systemd/boot/efi/systemd-bootx64.efi"
        efi.parent.mkdir(parents=True)
        efi.write_bytes(b"fixture payload")
    config = root / "usr/lib/ostree/prepare-root.conf"
    config.parent.mkdir(parents=True)
    config.write_text("[composefs]\nenabled = " + ("yes" if sealed else "no") + "\n")
    m = context / "fork-config.json"
    m.write_text(json.dumps(manifest()))
    original = SOURCE.read_json(root / SOURCE.RECIPE)
    SOURCE.finalize(m, root, context / SOURCE.PROBE)
    recipe = SOURCE.read_json(root / SOURCE.RECIPE)
    assert list(recipe["steps"]) == list(original["steps"])
    assert list(recipe["tour"]) == list(original["tour"])
    assert list(recipe["tour"]["welcome"]) == list(original["tour"]["welcome"])
    selected = SOURCE.selected_leaf(SOURCE.read_json(root / SOURCE.CATALOG), SOURCE.target_ref(manifest()))
    assert recipe["bootloader"] == selected["bootloader"] == ("grub2" if bootupd else "systemd")
    assert recipe["composeFsBackend"] is selected["composefs"] is (not bootupd)
    assert recipe["filesystem"] == selected["filesystem"] == ("ext4" if sealed else "xfs")
    before = (root / SOURCE.RECIPE).read_bytes()
    SOURCE.finalize(m, root, context / SOURCE.PROBE, verify_only=True)
    SOURCE.finalize(m, root, context / SOURCE.PROBE)
    assert (root / SOURCE.RECIPE).read_bytes() == before
    recipe["filesystem"] = "btrfs"
    (root / SOURCE.RECIPE).write_text(json.dumps(recipe))
    with pytest.raises(ValueError, match="measured"):
        SOURCE.finalize(m, root, context / SOURCE.PROBE, verify_only=True)


def test_unclassifiable_source_fails_without_mutation(tmp_path):
    context, root = tmp_path / "context", tmp_path / "root"
    prepare_root(context, root, manifest())
    (root / "usr/lib/bootupd/updates/EFI/test/grubx64.efi").unlink()
    m = context / "fork-config.json"
    m.write_text(json.dumps(manifest()))
    before = (root / SOURCE.RECIPE).read_bytes()
    with pytest.raises(subprocess.CalledProcessError):
        SOURCE.finalize(m, root, context / SOURCE.PROBE)
    assert (root / SOURCE.RECIPE).read_bytes() == before


def test_symlink_catalog_fails_before_recipe_mutation(tmp_path):
    context, root = tmp_path / "context", tmp_path / "root"
    prepare_root(context, root, manifest())
    outside = tmp_path / "outside.json"
    path = root / SOURCE.CATALOG
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    m = context / "fork-config.json"
    m.write_text(json.dumps(manifest()))
    before = (root / SOURCE.RECIPE).read_bytes()
    with pytest.raises(ValueError, match="symlink"):
        SOURCE.finalize(m, root, context / SOURCE.PROBE)
    assert (root / SOURCE.RECIPE).read_bytes() == before


def test_live_host_apply_is_denied_but_staging_authority_is_unchanged(tmp_path, monkeypatch):
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: False if path == Path("/run/.containerenv") else original(path))
    with pytest.raises(ValueError, match="Podman"):
        SOURCE.authorize_root(tmp_path / "fork-config.json", Path("/"))
    SOURCE.authorize_root(tmp_path / "fork-config.json", tmp_path)


def test_identity_container_apply_still_needs_exact_qualification(tmp_path, monkeypatch):
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: True if path == Path("/run/.containerenv") else original(path))
    (tmp_path / "fork-identity.json").write_text("{}")
    with pytest.raises(ValueError, match="qualification"):
        SOURCE.authorize_root(tmp_path / "fork-config.json", Path("/"))


def test_dangling_catalog_is_rejected_before_compile_writes(tmp_path):
    (tmp_path / "etc/bootc-installer").mkdir(parents=True)
    outside = tmp_path / "outside"
    (tmp_path / SOURCE.CATALOG).symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        SOURCE.safe_target(tmp_path, SOURCE.CATALOG)
    assert not outside.exists()


def test_qualified_context_precedes_installed_readonly_receipt(tmp_path, monkeypatch):
    helper = tmp_path / "fork-installer-source.py"
    monkeypatch.setattr(SOURCE, "__file__", str(helper))
    (tmp_path / "fork-identity.py").write_text("def qualification(path, container=False):\n    return container and path.name == 'fork-identity.json'\n")
    (tmp_path / "fork-identity.json").write_text("{}")
    manifest_path = tmp_path / "fork-config.json"
    manifest_path.write_text(json.dumps(manifest()))
    original_file, original_exists = Path.is_file, Path.exists
    monkeypatch.setattr(Path, "is_file", lambda p: True if p == Path("/run/.containerenv") else original_file(p))
    monkeypatch.setattr(Path, "exists", lambda p: True if p == Path("/usr/share/tunaos/fork-identity/manifest.json") else original_exists(p))
    SOURCE.authorize_root(manifest_path, Path("/"))


@pytest.mark.parametrize("change", ["tag", "recipe", "catalog", "probe"])
def test_build_entry_rejects_drift_before_a_builder_can_run(tmp_path, change):
    value = manifest()
    prepare_root(tmp_path, tmp_path / "system_files", value)
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests/fork-config.json").write_text(json.dumps(value))
    original = tmp_path / "live-iso/common/src/installer-recipe-backend.sh"
    original.parent.mkdir(parents=True)
    original.write_bytes((tmp_path / SOURCE.PROBE).read_bytes())
    target = SOURCE.target_ref(value)
    env = {"IMAGE_TAG": target, "IMAGE_REGISTRY": "localhost", "REPO_ORGANIZATION": "harbor",
           "VARIANT": "yellowfin", "PUBLIC_IMAGE_NAME": "yellowfin", "PLATFORM": "linux/amd64",
           "TUNAOS_IMAGE_FLAVOR": "gnome"}
    SOURCE.validate_entry(tmp_path, env)
    if change == "tag":
        env["IMAGE_TAG"] = "ghcr.io/unrelated/yellowfin:gnome"
    elif change == "probe":
        (tmp_path / SOURCE.PROBE).write_text("echo unreviewed\n")
    else:
        path = tmp_path / "system_files" / (SOURCE.RECIPE if change == "recipe" else SOURCE.CATALOG)
        data = SOURCE.read_json(path)
        data["imgref" if change == "recipe" else "default_image"] = "ghcr.io/tuna-os/tunaos:latest"
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        SOURCE.validate_entry(tmp_path, env)
