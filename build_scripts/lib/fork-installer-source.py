#!/usr/bin/env python3
"""Derive fork installer routing from the resolved cell, never stock defaults.

Build-time references contain no self-referential image digest. Finalized OCI
bytes are bound separately by the export verifier.
"""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

RECIPE = "etc/bootc-installer/recipe.json"
CATALOG = "etc/bootc-installer/images.json"
PROBE = "build_scripts/lib/installer-recipe-backend.sh"


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate installer source key: {key}")
        value[key] = item
    return value


def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"installer source requires a regular file: {path}")
    return json.loads(path.read_text(), object_pairs_hook=unique)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def target_ref(manifest):
    """The preparation tag is also the install/update destination, per platform."""
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("invalid resolved fork manifest")
    image = manifest.get("image")
    if not isinstance(image, dict) or set(image) != {"registry", "namespace"}:
        raise ValueError("fork image registry and namespace are required")
    fields = ((image.get("registry"), r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?"),
              (image.get("namespace"), r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"),
              (manifest.get("variant"), r"[a-z0-9][a-z0-9-]*"),
              (manifest.get("flavor"), r"[a-z0-9][a-z0-9-]*"))
    if any(not isinstance(value, str) or not re.fullmatch(pattern, value) for value, pattern in fields):
        raise ValueError("invalid resolved fork image reference")
    if ":" in image["registry"] and not 1 <= int(image["registry"].rsplit(":", 1)[1]) <= 65535:
        raise ValueError("invalid fork registry port")
    if manifest.get("platform") not in ("linux/amd64", "linux/amd64/v2", "linux/arm64"):
        raise ValueError("unsupported fork image platform")
    return f"{image['registry']}/{image['namespace']}/{manifest['variant']}:{manifest['flavor']}-{manifest['platform'].replace('/', '-')}"


def leaves(nodes, registry=""):
    """Match the frontend's explicit-ref / inherited registry+tag semantics."""
    if not isinstance(nodes, list):
        raise ValueError("installer catalog images/children must be a list")
    result = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("installer catalog node must be an object")
        registry_here = node.get("registry", registry)
        ref = node.get("imgref")
        if ref is None and "tag" in node:
            if not isinstance(registry_here, str) or not registry_here or not isinstance(node["tag"], str) or not node["tag"]:
                raise ValueError("installer catalog tag has no resolvable registry")
            ref = f"{registry_here}:{node['tag']}"
        if ref is not None:
            if not isinstance(ref, str) or not ref or "children" in node:
                raise ValueError("ambiguous installer catalog leaf")
            result.append((node, ref))
        else:
            result.extend(leaves(node.get("children", []), registry_here))
    return result


def selected_leaf(catalog, reference):
    if not isinstance(catalog, dict) or "images" not in catalog:
        raise ValueError("installer catalog must contain images")
    matches = [node for node, ref in leaves(catalog["images"]) if ref == reference]
    if len(matches) != 1:
        raise ValueError("installer target must match exactly one catalog leaf")
    return matches[0]


def project_catalog(catalog, old_ref, target, name):
    if catalog is None:
        return {"default_image": target, "fallback_flatpaks": [],
                "images": [{"name": name, "imgref": target}]}
    if not isinstance(catalog, dict):
        raise ValueError("installer catalog must be an object")
    catalog = copy.deepcopy(catalog)
    catalog.setdefault("fallback_flatpaks", [])
    matches = [(node, ref) for node, ref in leaves(catalog.get("images")) if ref in {old_ref, target}]
    if len(matches) != 1:
        raise ValueError("cannot resolve a unique existing installer catalog source")
    node, _ = matches[0]
    node["imgref"] = target
    node.pop("tag", None)
    node["name"] = name
    catalog["default_image"] = target
    return catalog


def project(manifest, recipe, catalog=None, name=None):
    target = target_ref(manifest)
    if not isinstance(recipe, dict) or not isinstance(recipe.get("imgref"), str) or not recipe["imgref"]:
        raise ValueError("installer recipe needs an explicit source imgref")
    recipe = copy.deepcopy(recipe)
    old_ref = recipe["imgref"]
    name = name or manifest["variant"]
    catalog = project_catalog(catalog, old_ref, target, name)
    # Some recipes carry their own catalog as well as the image screen's host
    # catalog. Both must resolve the same default; unrelated leaves survive.
    if "images" in recipe:
        routed = project_catalog({"images": recipe["images"]}, old_ref, target, name)
        recipe["images"] = routed["images"]
        for node, ref in leaves(recipe["images"]):
            if "default" in node or ref == target:
                node["default"] = ref == target
    recipe.update(imgref=target, local_imgref="containers-storage:" + target)
    if "targetImgref" in recipe:
        recipe["targetImgref"] = target
    verify(manifest, recipe, catalog)
    return recipe, catalog


def verify(manifest, recipe, catalog):
    target = target_ref(manifest)
    if (not isinstance(recipe, dict) or recipe.get("imgref") != target
            or recipe.get("local_imgref") != "containers-storage:" + target
            or recipe.get("targetImgref", target) != target):
        raise ValueError("installer recipe source/destination differs from resolved fork cell")
    if not isinstance(catalog, dict) or catalog.get("default_image") != target:
        raise ValueError("installer catalog default differs from resolved fork cell")
    selected_leaf(catalog, target)
    if "images" in recipe:
        selected = selected_leaf({"images": recipe["images"]}, target)
        defaults = [node for node, _ in leaves(recipe["images"]) if node.get("default")]
        if defaults != [selected]:
            raise ValueError("recipe catalog has an ambiguous default source")
    return target


def safe_target(root, relative):
    path = root / relative
    for candidate in [path, *path.parents]:
        if candidate == root:
            break
        if candidate.is_symlink():
            raise ValueError(f"symlinked installer target: {relative}")
        if candidate != path and candidate.exists() and not candidate.is_dir():
            raise ValueError(f"non-directory installer target ancestor: {relative}")
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError(f"non-regular or hardlinked installer target: {relative}")
    return path


def backend(probe, root):
    result = subprocess.check_output(["bash", str(probe), str(root)], text=True)
    pairs = [line.split("=", 1) for line in result.splitlines()]
    if any(len(pair) != 2 for pair in pairs):
        raise ValueError("invalid measured installer backend")
    values = unique(pairs)
    if (set(values) != {"bootloader", "composeFsBackend", "filesystem"}
            or values["bootloader"] not in ("grub2", "systemd")
            or values["composeFsBackend"] not in ("false", "true")
            or values["filesystem"] not in ("xfs", "ext4")):
        raise ValueError("invalid measured installer backend")
    values["composeFsBackend"] = values["composeFsBackend"] == "true"
    return values


def authorize_root(manifest_path, root):
    """Host writes stay blocked; paired identity retains its narrower authority."""
    if root != Path("/"):
        return
    if not Path("/run/.containerenv").is_file():
        raise ValueError("live-root installer writes require a Podman build container")
    candidates = [manifest_path.parent / "fork-identity.json",
                  root / "usr/share/tunaos/fork-identity/manifest.json"]
    for identity_path in candidates:
        if identity_path.exists() or identity_path.is_symlink():
            helper = Path(__file__).with_name("fork-identity.py")
            spec = importlib.util.spec_from_file_location("fork_identity_authority", helper)
            identity = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(identity)
            if not identity.qualification(identity_path, container=True):
                raise ValueError("live-root identity installer writes need exact qualification authority")
            if read_json(identity_path.parent / "fork-config.json") != read_json(manifest_path):
                raise ValueError("identity qualification does not match installer source manifest")
            # The qualified build context takes precedence over the immutable
            # installed receipt, which intentionally carries no build authority.
            return


def finalize(manifest_path, root, probe, check=False, verify_only=False):
    """Use the actual image's boot payload, before identity records its hashes."""
    root = root.resolve(strict=True)
    if not check and not verify_only:
        authorize_root(manifest_path, root)
    manifest = read_json(manifest_path)
    recipe_path, catalog_path = (safe_target(root, name) for name in (RECIPE, CATALOG))
    recipe, catalog = read_json(recipe_path), read_json(catalog_path)
    target = verify(manifest, recipe, catalog)
    originals = copy.deepcopy((recipe, catalog))
    for relative in ("usr/libexec/tunaos/fork-installer-source.py", "usr/libexec/tunaos/installer-recipe-backend.sh"):
        safe_target(root, relative)
    values = backend(probe, root)
    recipe.update(values)
    catalogs = [catalog]
    if "images" in recipe:
        catalogs.append({"images": recipe["images"]})
    for item in catalogs:
        # The image screen emits explicit false when composefs metadata is
        # absent. Populate its established key as well as the canonical recipe.
        selected_leaf(item, target).update(bootloader=values["bootloader"],
                                          composefs=values["composeFsBackend"], filesystem=values["filesystem"])
    if verify_only and (recipe, catalog) != originals:
        raise ValueError("installer recipe/catalog metadata differs from measured boot payload")
    if check or verify_only:
        return
    for path, value in ((recipe_path, recipe), (catalog_path, catalog)):
        path.write_bytes(json_bytes(value))


def validate_entry(context, env):
    manifest = read_json(context / "manifests/fork-config.json")
    target = verify(manifest, read_json(context / "system_files" / RECIPE),
                    read_json(context / "system_files" / CATALOG))
    expected = {"IMAGE_TAG": target, "IMAGE_REGISTRY": manifest["image"]["registry"],
                "REPO_ORGANIZATION": manifest["image"]["namespace"], "VARIANT": manifest["variant"],
                "PUBLIC_IMAGE_NAME": manifest["variant"], "PLATFORM": manifest["platform"],
                "TUNAOS_IMAGE_FLAVOR": manifest["flavor"]}
    if any(env.get(key) != value for key, value in expected.items()):
        raise ValueError("fork build environment differs from installer source/destination")
    copied = context / PROBE
    original = context / "live-iso/common/src/installer-recipe-backend.sh"
    if copied.is_symlink() or not copied.is_file() or copied.read_bytes() != original.read_bytes():
        raise ValueError("fork backend probe differs from canonical source")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-build-entry", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--backend-probe", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.validate_build_entry:
        validate_entry(Path.cwd(), os.environ)
    elif args.manifest and args.root and args.backend_probe:
        finalize(args.manifest, args.root, args.backend_probe, args.check, args.verify)
    else:
        parser.error("provide --validate-build-entry or --manifest, --root and --backend-probe")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: fork installer source: {exc}", file=sys.stderr)
        sys.exit(2)
