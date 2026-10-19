#!/usr/bin/env python3
"""Export one finalized fork image to a verified, digest-preserving local OCI dir.

No registry access, publication, credentials or modification of image contents.
The outside receipt binds build-time routing to finalized bytes without putting
an image's own digest into the image itself.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fork_source", ROOT / "build_scripts/lib/fork-installer-source.py")
SOURCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
MANIFEST_TYPES = {"application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"}
CONFIG_TYPES = {"application/vnd.oci.image.config.v1+json", "application/vnd.docker.container.image.v1+json"}
FILES = ("usr/share/tunaos/fork/fork-config.json", SOURCE.RECIPE, SOURCE.CATALOG)


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def regular(root, relative):
    path = root / relative
    for current in (path, *path.parents):
        if current == root:
            break
        if current.is_symlink():
            raise ValueError("OCI layout must not contain symlinked inputs")
    if not path.is_file():
        raise ValueError(f"OCI layout input is missing: {relative}")
    return path


def descriptor(layout, value, media_types=None):
    if (not isinstance(value, dict) or not isinstance(value.get("digest"), str)
            or not DIGEST.fullmatch(value["digest"]) or type(value.get("size")) is not int
            or value["size"] < 0 or value.get("urls")
            or (media_types is not None and value.get("mediaType") not in media_types)):
        raise ValueError("unsupported OCI descriptor")
    path = regular(layout, "blobs/sha256/" + value["digest"].split(":")[1])
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    if size != value["size"] or "sha256:" + digest.hexdigest() != value["digest"]:
        raise ValueError("OCI blob size or SHA-256 mismatch")
    return path


def object_json(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("OCI JSON exceeds bounded metadata size")
    value = SOURCE.read_json(path)
    if not isinstance(value, dict):
        raise ValueError("OCI metadata must be an object")
    return value


def verify_layout(layout, platform, source_manifest_digest, image_id):
    if layout.is_symlink() or not layout.is_dir():
        raise ValueError("OCI layout must be a regular directory")
    if object_json(regular(layout, "oci-layout")) != {"imageLayoutVersion": "1.0.0"}:
        raise ValueError("unsupported OCI layout version")
    index_path = regular(layout, "index.json")
    index = object_json(index_path)
    if index.get("schemaVersion") != 2 or not isinstance(index.get("manifests"), list) or len(index["manifests"]) != 1:
        raise ValueError("export requires exactly one platform manifest")
    selected = index["manifests"][0]
    manifest_path = descriptor(layout, selected, MANIFEST_TYPES)
    if selected["digest"] != source_manifest_digest:
        raise ValueError("export changed the finalized source manifest digest")
    manifest = object_json(manifest_path)
    if manifest.get("schemaVersion") != 2:
        raise ValueError("unsupported image manifest version")
    config_path = descriptor(layout, manifest.get("config"), CONFIG_TYPES)
    if manifest["config"]["digest"] != image_id:
        raise ValueError("exported config does not match inspected image ID")
    config = object_json(config_path)
    parts = platform.split("/")
    expected = {"os": parts[0], "architecture": parts[1]}
    if len(parts) == 3:
        expected["variant"] = parts[2]
    for key in ("os", "architecture", "variant"):
        if config.get(key, "") != expected.get(key, ""):
            raise ValueError("exported config platform differs from resolved fork cell")
    if "platform" in selected and (not isinstance(selected["platform"], dict) or any(
            selected["platform"].get(key, "") != expected.get(key, "") for key in ("os", "architecture", "variant"))):
        raise ValueError("OCI index platform differs from exported config")
    layers = manifest.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ValueError("OCI image must have layers")
    for layer in layers:
        descriptor(layout, layer)
    return {"manifest_digest": selected["digest"], "config_digest": manifest["config"]["digest"],
            "index_digest": sha(index_path.read_bytes()), "platform": platform,
            "layers": [{"digest": layer["digest"], "size": layer["size"]} for layer in layers]}


def embedded(image_id):
    # Resolve by config ID, never mutable tag. Do not execute the image's
    # entrypoint or give this evidence reader network or writable host mounts.
    program = ("import json,pathlib; print(json.dumps({p:pathlib.Path('/'+p).read_text() "
               "for p in " + repr(FILES) + "}))")
    command = ["podman", "run", "--rm", "--pull=never", "--network=none", "--read-only", "--cap-drop=all",
               "--entrypoint", "python3", image_id, "-c", program]
    value = json.loads(subprocess.check_output(command, text=True), object_pairs_hook=SOURCE.unique)
    if not isinstance(value, dict) or set(value) != set(FILES) or not all(isinstance(v, str) for v in value.values()):
        raise ValueError("image did not return the required embedded source receipts")
    subprocess.run(["podman", "run", "--rm", "--pull=never", "--network=none", "--read-only", "--cap-drop=all",
                    "--entrypoint", "python3", image_id, "/usr/libexec/tunaos/fork-installer-source.py",
                    "--manifest", "/" + FILES[0], "--root", "/",
                    "--backend-probe", "/usr/libexec/tunaos/installer-recipe-backend.sh", "--verify"], check=True)
    return value


def export(manifest_path, output):
    expected = SOURCE.read_json(manifest_path)
    output = output.absolute()
    for parent in (output, *output.parents):
        if parent.is_symlink():
            raise ValueError("export output must not have symlinked ancestors")
    if ":" in str(output):
        raise ValueError("OCI output path cannot contain a colon")
    target = SOURCE.target_ref(expected)
    if output.exists() or output.is_symlink():
        raise ValueError("export output must not already exist")
    info = json.loads(subprocess.check_output(["podman", "image", "inspect", target], text=True))
    if not isinstance(info, list) or len(info) != 1:
        raise ValueError("configured target did not resolve to one local image")
    if not isinstance(info[0], dict) or not isinstance(info[0].get("Id"), str):
        raise ValueError("local image has no valid config digest")
    image_id = info[0]["Id"]
    if not image_id.startswith("sha256:"):
        image_id = "sha256:" + image_id
    if not DIGEST.fullmatch(image_id):
        raise ValueError("local image has no valid config digest")
    files = embedded(image_id)
    parsed = {name: json.loads(value, object_pairs_hook=SOURCE.unique) for name, value in files.items()}
    if parsed[FILES[0]] != expected:
        raise ValueError("built image contains a different fork manifest")
    SOURCE.verify(expected, parsed[SOURCE.RECIPE], parsed[SOURCE.CATALOG])
    # containers/image storage IDs are bare 64-hex values; sha256:HEX would
    # parse as the repository sha256 with tag HEX, not an immutable ID.
    storage_ref = "containers-storage:@" + image_id.removeprefix("sha256:")
    raw = subprocess.check_output(["skopeo", "inspect", "--raw", storage_ref])
    original = json.loads(raw, object_pairs_hook=SOURCE.unique)
    if (not isinstance(original, dict) or original.get("schemaVersion") != 2
            or original.get("mediaType") not in MANIFEST_TYPES or "manifests" in original
            or not isinstance(original.get("config"), dict) or original["config"].get("digest") != image_id
            or original["config"].get("mediaType") not in CONFIG_TYPES
            or not isinstance(original.get("layers"), list) or not original["layers"]):
        raise ValueError("source must be a supported platform manifest for the inspected config")
    version = subprocess.check_output(["skopeo", "--version"], text=True).strip()
    output.mkdir(parents=True)
    layout = output / "source"
    command = ["skopeo", "copy", "--preserve-digests", storage_ref, "oci:" + str(layout) + ":canary"]
    subprocess.run(command, check=True)
    verified = verify_layout(layout, expected["platform"], sha(raw), image_id)
    receipt = {"schema_version": 1, "target_imgref": target, "original_local_imgref": parsed[SOURCE.RECIPE]["local_imgref"],
               "source_image_id": image_id, "source_manifest_digest": sha(raw), "preserved_digest": True,
               "source_receipt": expected["sources"], "fork_manifest_sha256": sha(files[FILES[0]].encode()),
               "recipe_sha256": sha(files[SOURCE.RECIPE].encode()), "catalog_sha256": sha(files[SOURCE.CATALOG].encode()),
               "storage": {key: parsed[SOURCE.RECIPE][key] for key in ("composeFsBackend", "bootloader", "filesystem")},
               "exporter": version, "export_command": command, "verified_oci": verified}
    (output / "source-manifest.json").write_bytes(raw)
    (output / "source-receipt.json").write_bytes(SOURCE.json_bytes(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="prepared manifests/fork-config.json")
    parser.add_argument("--output", type=Path, required=True, help="new export directory, never overwritten")
    args = parser.parse_args()
    print(json.dumps(export(args.manifest, args.output), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: fork source export: {exc}", file=sys.stderr)
        sys.exit(2)
