#!/usr/bin/env python3
"""Prepare isolated, pinned local desktop build contexts; never publish images.

This preview supports direct desktop routes only. It validates all selected
cells before writing. --build explicitly invokes the existing local build engine.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fork_config", ROOT / "scripts/resolve-fork-config.py")
COMPILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPILER)
ConfigError = COMPILER.ConfigError
# Routes, not a second variant catalog. Unknown future routes fail closed.
MANAGERS = {"Containerfile.el10": "dnf", "Containerfile.ubuntu": "apt",
            "Containerfile.debian": "apt", "Containerfile.arch": "pacman",
            "Containerfile.opensuse": "zypper", "Containerfile.gentoo": "emerge"}
PACKAGE = r"[A-Za-z0-9][A-Za-z0-9+_.-]*"
REPO_URL = r"https://[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~%+,:=@/-]*)?"
ARCHIVE = r"\.(rpm|deb|udeb|ebuild|tbz2|gpkg\.tar|pkg\.tar(\.[a-z0-9]+)?)$"


def validate_packages(packages, manager):
    COMPILER.validate_layer({"packages": packages}, "packages", Path("."))
    if packages["remove"]:
        raise ConfigError("package removals are not supported by this preview: solver/base protections required")
    pattern = PACKAGE + "/" + PACKAGE if manager == "emerge" else (
        r"[a-z0-9][a-z0-9+.-]*" if manager == "apt" else PACKAGE)
    for key in ("add", "optional"):
        for value in packages[key]:
            if not re.fullmatch(pattern, value) or re.search(ARCHIVE, value, re.I):
                raise ConfigError(f"{manager}: {value!r} is not a supported plain native package name")
    if packages["repositories"] and manager not in ("dnf", "zypper", "apt"):
        raise ConfigError(f"{manager}: custom repository semantics are not supported by this preview")
    for repo in packages["repositories"]:
        if (repo.get("type") == "apt") != (manager == "apt"):
            raise ConfigError(f"{manager}: repository semantics: type must match the selected package family")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", repo["id"]):
            raise ConfigError("repository id must be a lowercase filename-safe token")
        if any(not re.fullmatch(REPO_URL, repo[k]) for k in ("url", "key_url")):
            raise ConfigError("repository URLs must be literal HTTPS URLs without query/fragment/auth/interpolation")


def wallpaper(path):
    """Decode before build; no hidden dependencies in stock builds."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ConfigError("wallpaper validation requires Pillow on the preparation host") from exc
    data = path.read_bytes()
    if not 0 < len(data) <= 16 * 1024 * 1024:
        raise ConfigError("wallpaper must be between 1 byte and 16 MiB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "JPEG" or getattr(image, "n_frames", 1) != 1:
                raise ConfigError("wallpaper must be a single-frame JPEG")
            if not all(1 <= n <= 8192 for n in image.size):
                raise ConfigError("wallpaper dimensions must be 1..8192 pixels")
            extension = "jpg"
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ConfigError(f"invalid wallpaper: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    return {"path": f"fork-assets/{digest}.{extension}", "sha256": digest}, data


def compile_cells(config_path, root=ROOT, identity_staging=False):
    config = yaml.load(config_path.read_text(), Loader=COMPILER.UniqueLoader)
    plan = COMPILER.resolve(config, config_path.parent, root)
    if not config.get("targets"):
        raise ConfigError("preview requires explicit targets; select direct desktop flavors")
    cells = []
    assets = {}
    for cell in plan["cells"]:
        if not cell["selected"] or not cell["build_image"]:
            continue
        routing = cell["routing"]
        containerfile = routing["CONTAINERFILE"]
        flavor = cell["flavor"]
        if (containerfile not in MANAGERS or routing["PARENT_FLAVOR"] or
                not (root / "manifests/desktops" / (flavor + ".yaml")).is_file() or
                flavor != routing["DESKTOP_FLAVOR"]):
            raise ConfigError(f"{cell['variant']}:{flavor}: only direct manifest-backed desktop routes are supported; base/overlay closure is deferred")
        manager = MANAGERS[containerfile]
        validate_packages(cell["intent"]["packages"], manager)
        branding = cell["intent"]["branding"]
        if identity_staging and not {"name", "logo"}.issubset(branding):
            raise ConfigError("identity staging needs both name and logo in every selected enabled cell")
        identity = None
        if set(branding) & {"name", "logo"}:
            if not identity_staging:
                raise ConfigError("name/logo customization is deferred until embedded installer and Plymouth assets are integrated; use --identity-staging for non-buildable root staging")
            spec = importlib.util.spec_from_file_location("prepare_identity", root / "scripts/prepare-fork-identity.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            try:
                identity, blobs = module.prepare(branding, cell, config_path.parent, plan["sources"]["sha256"])
            except (ValueError, ImportError, OSError) as exc:
                raise ConfigError(f"identity staging: {exc}") from exc
            assets.update(blobs)
            # Internal URL/package adapter retains its closed contract. The
            # separate identity payload records all name/logo intent and hashes.
            cell = {**cell, "intent": {**cell["intent"], "branding": {
                key: value for key, value in branding.items() if key not in ("name", "logo")}}}
        cell_assets = {}
        if "wallpaper" in branding:
            if flavor == "tuna":
                raise ConfigError("tuna wallpaper customization is deferred until its desktop setting consumer is verified")
            asset, data = wallpaper(config_path.parent / branding["wallpaper"])
            cell_assets["wallpaper"] = asset
            assets[asset["path"]] = data
        base = subprocess.check_output(["bash", str(root / "scripts/get-base-image.sh"),
                                        cell["variant"], cell["platform"]], text=True).strip()
        if not base or any(char.isspace() for char in base):
            raise ConfigError("base resolver returned an invalid image reference")
        base_pinned = bool(re.search(r"@sha256:[0-9a-f]{64}$", base))
        image = config.get("image", {"registry": "localhost", "namespace": "fork-preview"})
        manifest = {"schema_version": 1, "image": image, **{k: cell[k] for k in ("variant", "flavor", "platform")},
                    "package_manager": manager, "intent": cell["intent"],
                    "sources": {"sha256": plan["sources"]["sha256"]}, "assets": cell_assets}
        # One local tag per architecture avoids overwriting earlier fanout results.
        tag = f"{image['registry']}/{image['namespace']}/{cell['variant']}:{flavor}-{cell['platform'].replace('/', '-')}"
        env = {"IMAGE_TAG": tag, "VARIANT": cell["variant"], "PUBLIC_IMAGE_NAME": cell["variant"],
               "CONTAINERFILE": containerfile, "BASE_IMAGE": base, "PLATFORM": cell["platform"],
               "DESKTOP_FLAVOR": routing["DESKTOP_FLAVOR"], "TUNAOS_IMAGE_FLAVOR": flavor,
               "ENABLE_HWE": "0", "ENABLE_NVIDIA": "0", "ENABLE_ASAHI": "0", "ENABLE_SSHD": "0",
               "IMAGE_REGISTRY": image["registry"], "REPO_ORGANIZATION": image["namespace"],
               "USE_CACHE": "0", "IS_CI": "0", "SKIP_RECHUNK": "1", "SKIP_SUBMODULES": "1"}
        cells.append({"manifest": manifest, "environment": env, "base_digest_pinned": base_pinned,
                      **({"identity": identity} if identity else {})})
    return plan, cells, assets


def prepare(config_path, output, root=ROOT, identity_staging=False):
    reserved = tuple(root / "manifests" / name for name in (
        "fork-config.json", "fork-assets", "fork-identity.json", "fork-identity-assets"))
    if any(path.exists() or path.is_symlink() for path in reserved):
        raise ConfigError("source checkout contains reserved generated fork payload paths; use a clean source checkout")
    plan, cells, assets = compile_cells(config_path, root, identity_staging)
    if output.exists() or output.is_symlink():
        raise ConfigError("output must not already exist; prepared contexts are never overwritten")
    if output.resolve().is_relative_to(root.resolve()):
        raise ConfigError("output must be outside the source checkout")
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"], text=True).split("\0")
    # Copy only reviewed source bytes, never untracked files, credentials or .git.
    output.mkdir(parents=True)
    (output / "source-receipt.json").write_text(json.dumps(plan["sources"], indent=2) + "\n")
    (output / "review-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    builds = []
    for cell in cells:
        manifest = cell["manifest"]
        name = "--".join(manifest[k].replace("/", "-") for k in ("variant", "flavor", "platform"))
        context = output / name
        context.mkdir()
        for relative in filter(None, tracked):
            src, dst = root / relative, context / relative
            if src.is_dir():
                raise ConfigError(f"submodule/directory source needs an explicit receipt: {relative}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink():
                dst.symlink_to(os.readlink(src))
            else:
                shutil.copy2(src, dst)
        subprocess.run(["git", "init", "-q", str(context)], check=True)
        subprocess.run(["git", "-C", str(context), "add", "--all"], check=True)
        if COMPILER.source_receipt(context) != plan["sources"]:
            raise ConfigError("sources changed during preparation; discard output and retry after review")
        (context / "manifests/fork-config.json").write_text(json.dumps(manifest, indent=2) + "\n")
        cell_assets = list(manifest["assets"].values())
        if "identity" in cell:
            (context / "manifests/fork-identity.json").write_text(json.dumps(cell["identity"], indent=2) + "\n")
            cell_assets += list(cell["identity"]["assets"].values())
        for asset in cell_assets:
            destination = context / "manifests" / asset["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(assets[asset["path"]])
        builds.append({"context": name, "environment": cell["environment"],
                       "base_digest_pinned": cell["base_digest_pinned"],
                       **({"build_blocked": cell["identity"]["blocked_consumers"]} if "identity" in cell else {})})
    (output / "builds.json").write_text(json.dumps(builds, indent=2) + "\n")
    return builds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--build", action="store_true", help="build every prepared cell locally; no push/release")
    parser.add_argument("--identity-staging", action="store_true", help="prepare name/logo staging inputs; never buildable images")
    args = parser.parse_args()
    try:
        if args.identity_staging and args.build:
            raise ConfigError("identity staging cannot build: installer, Plymouth and image qualification are incomplete")
        options = {"identity_staging": True} if args.identity_staging else {}
        builds = prepare(args.config.resolve(), args.output.resolve(), **options)
        print(f"Prepared {len(builds)} local preview contexts in {args.output}")
        for build in builds:
            if build.get("build_blocked"):
                print(f"BLOCKED: {build['context']} is identity staging only: " + ", ".join(build["build_blocked"]), file=sys.stderr)
            if not build["base_digest_pinned"]:
                print(f"WARNING: {build['context']} retains a mutable upstream base: {build['environment']['BASE_IMAGE']}", file=sys.stderr)
        if args.build:
            for build in builds:
                env = dict(os.environ)
                # Do not let a caller-selected alternate catalog alter a validated context.
                for key in list(env):
                    if key in {"TUNAOS_BUILD_CONFIG", "COMMON_IMAGE", "BREW_IMAGE",
                               "UTAH_PACKAGES_IMAGE", "GNOME50_EL10_PACKAGES_IMAGE",
                               "BUILDAH_CACHE_FLAGS", "OVERLAY_TYPE", "COREOS_STABLE_VERSION",
                               "RHSM_USER", "RHSM_PASSWORD", "RHSM_ORG", "RHSM_ACTIVATION_KEY",
                               "BASH_ENV", "ENV"} or key.startswith(("TUNA_REGISTRY_", "TUNA_IMAGE_", "BASH_FUNC_")):
                        env.pop(key)
                env.update(build["environment"])
                subprocess.run(["bash", "scripts/build-image-inner.sh"],
                               cwd=args.output / build["context"], env=env, check=True)
    except (ConfigError, OSError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
