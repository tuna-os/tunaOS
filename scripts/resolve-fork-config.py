#!/usr/bin/env python3
"""Validate the v1 fork intent contract and emit a non-executable review plan.

Only --format legacy supports build consumption, and only for stock intent.
Requires PyYAML, already used by the repository's Python tooling.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


class ConfigError(ValueError):
    """An invalid or not-yet-supported fork intent."""


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently accepting the last value."""


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ConfigError(f"duplicate or non-string YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def mapping(value, allowed, where, required=()):
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected a mapping")
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown or missing:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}")
    return value


def string(value, where):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ConfigError(f"{where}: expected a nonempty single-line string")
    return value


def strings(value, where):
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where}: expected a nonempty list")
    for item in value:
        string(item, where)
    if len(set(value)) != len(value):
        raise ConfigError(f"{where}: duplicate values")
    return value


def source_paths(root):
    """Source receipt, not a second package or variant catalog."""
    patterns = (".github/build-config.yml", "image-versions.yaml", "registry-map.yaml",
                "Containerfile*", "manifests/**/*", "build_scripts/**/*", "scripts/**/*",
                "Justfile", "just/**/*", ".containerignore", ".dockerignore", "custom/**/*",
                "system_files/**/*", "system_files_overrides/**/*", "experiences/**/*",
                "live-iso/common/src/installer-recipe-backend.sh")
    tracked = set(subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"], text=True).split("\0"))
    return sorted({p.relative_to(root).as_posix() for pattern in patterns
                   for p in root.glob(pattern)
                   if (p.is_file() or p.is_symlink()) and p.relative_to(root).as_posix() in tracked})


def source_receipt(root):
    files = {}
    modes = {}
    for name in source_paths(root):
        path = root / name
        content = b"symlink:" + os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        files[name] = hashlib.sha256(content).hexdigest()
        modes[name] = "120000" if path.is_symlink() else ("100755" if path.stat().st_mode & 0o111 else "100644")
    payload = {"files": files, "modes": modes}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"sha256": digest, **payload}


def validate_layer(value, where, config_dir):
    mapping(value, ("branding", "packages"), where)
    if "branding" in value:
        branding = mapping(value["branding"],
                           ("name", "homepage", "documentation", "support", "logo", "wallpaper"),
                           where + ".branding")
        for key, val in branding.items():
            string(val, where + ".branding." + key)
            if key in ("homepage", "documentation", "support") and not re.fullmatch(r"https://[^\s/]+(?:/[^\s]*)?", val):
                raise ConfigError(f"{where}.branding.{key}: expected an HTTPS URL")
            if key in ("logo", "wallpaper"):
                path = (config_dir / val).resolve()
                if Path(val).is_absolute() or not path.is_relative_to(config_dir.resolve()) or not path.is_file():
                    raise ConfigError(f"{where}.branding.{key}: expected an existing config-relative asset")
    if "packages" in value:
        packages = mapping(value["packages"], ("add", "remove", "optional", "repositories"), where + ".packages")
        for key, vals in packages.items():
            if not isinstance(vals, list):
                raise ConfigError(f"{where}.packages.{key}: expected a list")
            if key != "repositories":
                if vals:
                    strings(vals, where + ".packages." + key)
                continue
            ids = set()
            for repo in vals:
                mapping(repo, ("id", "url", "key_url"), where + ".repositories", ("id", "url", "key_url"))
                for field, val in repo.items():
                    string(val, where + ".repositories." + field)
                    if field != "id" and not re.fullmatch(r"https://[^\s/]+(?:/[^\s]*)?", val):
                        raise ConfigError(f"{where}.repositories.{field}: expected an HTTPS URL")
                if repo["id"] in ids:
                    raise ConfigError(f"{where}: duplicate repository id {repo['id']}")
                ids.add(repo["id"])


def merge_layers(layers):
    result = {"branding": {}, "packages": {k: [] for k in ("repositories", "remove", "add", "optional")}}
    for layer in layers:
        result["branding"].update(layer.get("branding", {}))
        for key, vals in layer.get("packages", {}).items():
            for val in vals:
                if val not in result["packages"][key]:
                    result["packages"][key].append(val)
    packages = result["packages"]
    for left, right in (("add", "remove"), ("optional", "remove"), ("add", "optional")):
        conflict = set(packages[left]) & set(packages[right])
        if conflict:
            raise ConfigError(f"conflicting package operations {left}/{right}: {sorted(conflict)}")
    repos = packages["repositories"]
    if len({r["id"] for r in repos}) != len(repos):
        raise ConfigError("conflicting inherited repository declarations")
    return result


def load_catalog(root):
    # Use the same provider-neutral seam as existing image consumers. Do not
    # interpret a user-selected path independently from the shell library.
    path = subprocess.check_output(
        ["bash", "-c", 'source "$1"; tunaos_build_config', "--", str(root / "scripts/lib/build-config.sh")],
        text=True).strip()
    catalog = yaml.safe_load(Path(path).read_text())
    if not isinstance(catalog, dict) or not isinstance(catalog.get("variants"), list):
        raise ConfigError("build catalog must contain variants")
    return catalog, Path(path)


def resolve(config, config_dir, root=ROOT):
    mapping(config, ("schema_version", "catalog", "image", "targets", "global", "overrides"),
            "config", ("schema_version", "catalog"))
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ConfigError("schema_version: expected integer 1")
    pin = mapping(config["catalog"], ("sha256",), "catalog", ("sha256",))["sha256"]
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ConfigError("catalog.sha256: expected a lowercase SHA-256")
    receipt = source_receipt(root)
    if pin != receipt["sha256"]:
        raise ConfigError("catalog pin mismatch; review upstream source changes before updating the pin")
    catalog, catalog_path = load_catalog(root)
    # An environment override is supported only when byte-identical to the
    # pinned catalog. Otherwise the source receipt would falsely attest it.
    if catalog_path.read_bytes() != (root / ".github/build-config.yml").read_bytes():
        raise ConfigError("TUNAOS_BUILD_CONFIG differs from the pinned catalog")
    if "image" in config:
        image = mapping(config["image"], ("registry", "namespace"), "image", ("registry", "namespace"))
        for key, value in image.items():
            string(value, "image." + key)
            pattern = r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?" if key == "registry" else r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
            if not re.fullmatch(pattern, value):
                raise ConfigError(f"image.{key}: invalid registry/namespace token")
            if key == "registry" and ":" in value and not 1 <= int(value.rsplit(":", 1)[1]) <= 65535:
                raise ConfigError("image.registry: invalid port")
    variants = {v["id"]: v for v in catalog["variants"]}
    flavors = {f["id"] for v in variants.values() for f in v["flavors"]}
    platforms = {p for v in variants.values() for f in v["flavors"] for p in f.get("platforms", v.get("platforms", catalog["config"]["global_platforms"]))}
    targets = mapping(config.get("targets", {}), ("variants", "flavors", "platforms"), "targets")
    for key, known in (("variants", set(variants)), ("flavors", flavors), ("platforms", platforms)):
        if key in targets and not set(strings(targets[key], "targets." + key)) <= known:
            raise ConfigError(f"targets.{key}: unknown target")
    global_layer = config.get("global", {})
    validate_layer(global_layer, "global", config_dir)
    overrides = mapping(config.get("overrides", {}), ("variants", "desktops", "cells"), "overrides")
    # Desktop identity is sourced from the existing manifest names. Suffixes
    # identify family-specific manifests; they are not desktop selectors.
    desktops = {p.stem for p in (root / "manifests/desktops").glob("*.yaml") if p.stem in flavors}
    cells = {v["id"] + ":" + f["id"] for v in variants.values() for f in v["flavors"]}
    for scope, known in (("variants", set(variants)), ("desktops", desktops), ("cells", cells)):
        values = overrides.get(scope, {})
        mapping(values, known, "overrides." + scope)
        for key, val in values.items():
            validate_layer(val, "overrides." + scope + "." + key, config_dir)
    expanded = []
    for variant in variants.values():
        for flavor in variant["flavors"]:
            # Reuse routing rather than copying variant-to-Containerfile rules.
            output = subprocess.check_output(["bash", str(root / "scripts/resolve-flavor.sh"), variant["id"], flavor["id"]], text=True)
            routing = dict(line.split("=", 1) for line in output.splitlines())
            routing = {k: json.loads(v) for k, v in routing.items()}
            desktop = next((name for name in sorted(desktops, key=len, reverse=True)
                            if flavor["id"] == name or flavor["id"].startswith(name + "-")), None)
            key = variant["id"] + ":" + flavor["id"]
            intent = merge_layers([global_layer, overrides.get("variants", {}).get(variant["id"], {}),
                                   overrides.get("desktops", {}).get(desktop, {}),
                                   overrides.get("cells", {}).get(key, {})])
            for platform in flavor.get("platforms", variant.get("platforms", catalog["config"]["global_platforms"])):
                selected = all(key not in targets or value in targets[key] for key, value in
                               (("variants", variant["id"]), ("flavors", flavor["id"]), ("platforms", platform)))
                expanded.append({"variant": variant["id"], "flavor": flavor["id"], "platform": platform,
                                 "selected": selected, "build_image": flavor.get("build_image", False),
                                 "routing": routing, "intent": intent})
    if not any(cell["selected"] and cell["build_image"] for cell in expanded):
        raise ConfigError("targets select no enabled catalog cells")
    return {"plan_version": 1, "mode": "review-only", "consumers_integrated": False,
            "sources": receipt, "legacy_catalog": copy.deepcopy(catalog), "cells": expanded,
            "image_intent": config.get("image", {}),
            "package_resolution": "deferred: source receipt is not an effective package transaction"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, nargs="?")
    parser.add_argument("--init-template", type=Path, help="create a NEW pinned config from a template without catalog; never refresh existing pins")
    parser.add_argument("--catalog-pin", action="store_true", help="print the current source receipt digest")
    parser.add_argument("--format", choices=("plan", "legacy"), default="plan")
    args = parser.parse_args()
    try:
        if args.init_template:
            if args.config or args.catalog_pin or args.format != "plan":
                parser.error("--init-template cannot be combined with config, --catalog-pin or --format")
            template = yaml.load(args.init_template.read_text(), Loader=UniqueLoader)
            if not isinstance(template, dict) or "catalog" in template:
                raise ConfigError("initialization requires a template without catalog; existing config pins must be reviewed manually")
            template = {**template, "catalog": {"sha256": source_receipt(ROOT)["sha256"]}}
            resolve(template, args.init_template.parent)
            print(yaml.safe_dump(template, sort_keys=False), end="")
            return
        if args.catalog_pin:
            if args.config or args.format != "plan":
                parser.error("--catalog-pin cannot be combined with config or --format")
            print(source_receipt(ROOT)["sha256"])
            return
        if not args.config:
            parser.error("config is required")
        config = yaml.load(args.config.read_text(), Loader=UniqueLoader)
        plan = resolve(config, args.config.parent)
        if args.format == "legacy":
            if any(config.get(k) for k in ("image", "targets", "global", "overrides")):
                raise ConfigError("legacy adapter accepts stock intent only; fork consumers are not integrated")
            # JSON is YAML-compatible, preserving every source key and hold.
            print(json.dumps(plan["legacy_catalog"], indent=2, ensure_ascii=False))
        else:
            print(json.dumps(plan, indent=2, ensure_ascii=False))
    except (ConfigError, OSError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
