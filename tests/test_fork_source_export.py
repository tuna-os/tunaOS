"""Exercise byte-level export validation; stubs do not prove native OCI export."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_fork_installer_source import SOURCE, manifest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fork_export", ROOT / "scripts/export-fork-source.py")
EXPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORT)


def make_layout(path, platform="linux/amd64"):
    (path / "blobs/sha256").mkdir(parents=True)
    def blob(data, kind):
        digest = EXPORT.sha(data)
        (path / "blobs/sha256" / digest.split(":")[1]).write_bytes(data)
        return {"mediaType": kind, "digest": digest, "size": len(data)}
    config = blob(json.dumps({"os": "linux", "architecture": platform.split("/")[1]}).encode(), "application/vnd.oci.image.config.v1+json")
    layer = blob(b"exact layer bytes", "application/vnd.oci.image.layer.v1.tar")
    raw = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json", "config": config, "layers": [layer]}).encode()
    descriptor = blob(raw, "application/vnd.oci.image.manifest.v1+json")
    descriptor["platform"] = {"os": "linux", "architecture": platform.split("/")[1]}
    (path / "index.json").write_text(json.dumps({"schemaVersion": 2, "manifests": [descriptor]}))
    (path / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')
    return raw, config["digest"], layer


def test_layout_binds_manifest_config_platform_and_every_blob(tmp_path):
    raw, image_id, layer = make_layout(tmp_path / "source")
    result = EXPORT.verify_layout(tmp_path / "source", "linux/amd64", EXPORT.sha(raw), image_id)
    assert result["manifest_digest"] == EXPORT.sha(raw)
    assert result["config_digest"] == image_id
    assert result["index_digest"] != result["manifest_digest"]
    assert result["layers"] == [{"digest": layer["digest"], "size": layer["size"]}]


@pytest.mark.parametrize("corruption", ["layer", "config", "symlink", "wrong-manifest", "wrong-id", "wrong-arch", "multi-manifest", "index-platform"])
def test_export_corruption_fails_closed(tmp_path, corruption):
    layout = tmp_path / "source"
    raw, image_id, layer = make_layout(layout)
    source_digest = EXPORT.sha(raw)
    platform = "linux/amd64"
    if corruption in ("layer", "config", "symlink"):
        path = layout / "blobs/sha256" / (image_id if corruption == "config" else layer["digest"]).split(":")[1]
        if corruption == "symlink":
            outside = tmp_path / "outside"
            outside.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(outside)
        else:
            path.write_bytes(b"x" * path.stat().st_size)
    elif corruption == "wrong-manifest":
        source_digest = "sha256:" + "f" * 64
    elif corruption == "wrong-id":
        image_id = "sha256:" + "f" * 64
    elif corruption == "wrong-arch":
        platform = "linux/arm64"
    else:
        index = json.loads((layout / "index.json").read_text())
        if corruption == "multi-manifest":
            index["manifests"].append(copy.deepcopy(index["manifests"][0]))
        else:
            index["manifests"][0]["platform"]["architecture"] = "arm64"
        (layout / "index.json").write_text(json.dumps(index))
    with pytest.raises(ValueError):
        EXPORT.verify_layout(layout, platform, source_digest, image_id)


def test_full_export_pins_config_id_and_no_registry_or_image_mutation(tmp_path, monkeypatch):
    expected = manifest()
    expected["sources"] = {"sha256": "b" * 64}
    manifest_path = tmp_path / "fork-config.json"
    manifest_path.write_text(json.dumps(expected))
    fixture = tmp_path / "fixture"
    raw, image_id, _ = make_layout(fixture)
    recipe, catalog = SOURCE.project(expected, {"imgref": "stock:latest"})
    recipe.update(composeFsBackend=False, bootloader="grub2", filesystem="xfs")
    embedded = {EXPORT.FILES[0]: json.dumps(expected), SOURCE.RECIPE: json.dumps(recipe), SOURCE.CATALOG: json.dumps(catalog)}
    calls = []
    def output(command, **kwargs):
        calls.append(command)
        if command[:3] == ["podman", "image", "inspect"]:
            assert command[3] == SOURCE.target_ref(expected)
            return json.dumps([{"Id": image_id}])
        if command[:3] == ["skopeo", "inspect", "--raw"]:
            assert command[-1] == "containers-storage:@" + image_id.removeprefix("sha256:")
            return raw
        if command == ["skopeo", "--version"]:
            return "skopeo version test"
        if command[:2] == ["podman", "run"]:
            assert "--pull=never" in command and "--network=none" in command and "--read-only" in command
            assert image_id in command and SOURCE.target_ref(expected) not in command
            return json.dumps(embedded)
        pytest.fail(str(command))
    def run(command, **kwargs):
        import shutil
        calls.append(command)
        if command[:2] == ["skopeo", "copy"]:
            assert command[2:4] == ["--preserve-digests", "containers-storage:@" + image_id.removeprefix("sha256:")]
            assert command[-1] == "oci:" + str(tmp_path / "export/source") + ":canary"
            shutil.copytree(fixture, tmp_path / "export/source")
        else:
            assert command[:2] == ["podman", "run"] and image_id in command and command[-1] == "--verify"
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(subprocess, "check_output", output)
    monkeypatch.setattr(subprocess, "run", run)
    receipt = EXPORT.export(manifest_path, tmp_path / "export")
    assert receipt["source_image_id"] == image_id and receipt["preserved_digest"]
    assert receipt["source_manifest_digest"] == receipt["verified_oci"]["manifest_digest"] == EXPORT.sha(raw)
    assert receipt["target_imgref"] == SOURCE.target_ref(expected)
    assert receipt["storage"] == {"composeFsBackend": False, "bootloader": "grub2", "filesystem": "xfs"}
    assert len([c for c in calls if c[:3] == ["podman", "image", "inspect"]]) == 1
    assert not any("push" in c or "login" in c or "docker://" in " ".join(c) for c in calls)


def test_export_rejects_existing_output_without_commands(tmp_path, monkeypatch):
    source = tmp_path / "fork-config.json"
    source.write_text(json.dumps(manifest()))
    output = tmp_path / "existing"
    output.mkdir()
    def forbidden(*args, **kwargs):
        pytest.fail("existing export must fail before commands")
    monkeypatch.setattr(subprocess, "check_output", forbidden)
    with pytest.raises(ValueError, match="already exist"):
        EXPORT.export(source, output)


def test_export_refuses_symlinked_output_ancestors(tmp_path, monkeypatch):
    source = tmp_path / "fork-config.json"
    source.write_text(json.dumps(manifest()))
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    def forbidden(*args, **kwargs):
        pytest.fail("symlinked export must fail before commands")
    monkeypatch.setattr(subprocess, "check_output", forbidden)
    with pytest.raises(ValueError, match="symlinked"):
        EXPORT.export(source, link / "export")
    assert not list(outside.iterdir())


@pytest.mark.parametrize("image_id", [None, {}, 12, "bad"])
def test_inspect_id_must_be_a_digest_before_container_runs(tmp_path, monkeypatch, image_id):
    source = tmp_path / "fork-config.json"
    source.write_text(json.dumps(manifest()))
    calls = []
    def output(command, **kwargs):
        calls.append(command)
        assert command[:3] == ["podman", "image", "inspect"]
        return json.dumps([{"Id": image_id}])
    monkeypatch.setattr(subprocess, "check_output", output)
    with pytest.raises(ValueError, match="config digest"):
        EXPORT.export(source, tmp_path / "export")
    assert len(calls) == 1 and not (tmp_path / "export").exists()


@pytest.mark.parametrize("corruption", ["index", "schema", "config", "layers"])
def test_original_must_be_one_supported_platform_manifest_before_export(tmp_path, monkeypatch, corruption):
    expected = manifest()
    source = tmp_path / "fork-config.json"
    source.write_text(json.dumps(expected))
    raw, image_id, _ = make_layout(tmp_path / "fixture")
    original = json.loads(raw)
    if corruption == "index":
        original = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": []}
    elif corruption == "schema":
        original["schemaVersion"] = 1
    elif corruption == "config":
        original["config"] = []
    else:
        original["layers"] = []
    recipe, catalog = SOURCE.project(expected, {"imgref": "stock:latest"})
    monkeypatch.setattr(EXPORT, "embedded", lambda _: {EXPORT.FILES[0]: json.dumps(expected),
                                                     SOURCE.RECIPE: json.dumps(recipe), SOURCE.CATALOG: json.dumps(catalog)})
    def output(command, **kwargs):
        if command[:3] == ["podman", "image", "inspect"]:
            return json.dumps([{"Id": image_id}])
        assert command == ["skopeo", "inspect", "--raw", "containers-storage:@" + image_id.removeprefix("sha256:")]
        return json.dumps(original).encode()
    monkeypatch.setattr(subprocess, "check_output", output)
    with pytest.raises(ValueError, match="platform manifest"):
        EXPORT.export(source, tmp_path / "export")
    assert not (tmp_path / "export").exists()
