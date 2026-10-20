#!/usr/bin/env python3
"""Collect immutable delivery inputs at the publication decision point.

This is intentionally separate from catalog-facts.py. A qualification snapshot
is historical evidence; publication gates must compare it with the image,
live-overlay, and builder inputs visible now. A failed probe exits nonzero so
callers can leave publication enabled rather than suppressing an upload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import tunaos_config

import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERLAY_FLAVOR = re.compile(
    r"^(gnome|kde|cosmic|niri|xfce|pantheon|tuna)"
    r"(-(hwe|nvidia|nvidia-hwe|cachyos|zfs))?$"
)
VERSIONS = ROOT / "image-versions.yaml"


def _run(*args: str) -> str:
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"command failed: {' '.join(args)}") from exc


def _digest(value: str, where: str) -> str:
    if not value.startswith("sha256:") or len(value) != 71:
        raise RuntimeError(f"{where}: invalid digest {value!r}")
    return value


def _platform_parts(platform: str) -> tuple[str, str, str | None]:
    parts = platform.split("/")
    if len(parts) not in (2, 3) or parts[0] != "linux":
        raise RuntimeError(f"unsupported target platform: {platform}")
    return parts[0], parts[1], parts[2] if len(parts) == 3 else None


def _platform_matches(actual: dict[str, Any], wanted: str) -> bool:
    os_name, arch, variant = _platform_parts(wanted)
    if actual.get("os") != os_name or actual.get("architecture") != arch:
        return False
    actual_variant = actual.get("variant") or None
    if arch == "arm64" and variant is None:
        return actual_variant in (None, "v8")
    return actual_variant == variant


def _variant_config(config: dict[str, Any], variant: str) -> dict[str, Any]:
    for item in config.get("variants", []):
        if isinstance(item, dict) and item.get("id") == variant:
            return item
    raise RuntimeError(f"unknown variant: {variant}")


def _image_identity(config: dict[str, Any], variant: str, flavor: str, platform: str) -> dict[str, Any]:
    variant_cfg = _variant_config(config, variant)
    publish_name = variant_cfg.get("publish_name") or variant
    tag = flavor
    suffix = variant_cfg.get("tag_suffix") or ""
    if suffix and not tag.endswith(f"-{suffix}"):
        tag = f"{tag}-{suffix}"
    repository = f"ghcr.io/tuna-os/{publish_name}"
    reference = f"{repository}:{tag}"
    raw = json.loads(_run("skopeo", "inspect", "--raw", f"docker://{reference}"))
    manifests = raw.get("manifests")
    manifest_digest: str | None = None
    index_digest: str | None = None
    if isinstance(manifests, list):
        index_digest = _digest(
            _run("skopeo", "inspect", "--format", "{{.Digest}}", f"docker://{reference}"),
            reference,
        )
        for item in manifests:
            if isinstance(item, dict) and _platform_matches(item.get("platform") or {}, platform):
                manifest_digest = item.get("digest")
                break
        if manifest_digest is None:
            raise RuntimeError(f"{reference}: no manifest for {platform}")
    else:
        config_doc = json.loads(_run("skopeo", "inspect", "--config", f"docker://{reference}"))
        if not _platform_matches(config_doc, platform):
            raise RuntimeError(f"{reference}: manifest platform does not match {platform}")
        manifest_digest = _run(
            "skopeo", "inspect", "--format", "{{.Digest}}", f"docker://{reference}"
        )
    manifest_digest = _digest(str(manifest_digest), f"{reference}@{platform}")
    return {
        "variant": variant,
        "flavor": flavor,
        "platform": platform,
        "repository": repository,
        "tag": tag,
        "platformManifestDigest": manifest_digest,
        "indexDigest": index_digest,
        "platformDigest": manifest_digest,
    }


def _overlay_identity(variant: str, flavor: str, platform: str, base_digest: str) -> dict[str, Any]:
    safe = platform.replace("/", "-")
    reference = f"ghcr.io/tuna-os/live-overlay:{variant}-{flavor}-{safe}"
    output = json.loads(_run("skopeo", "inspect", f"docker://{reference}"))
    digest = _digest(str(output.get("Digest", "")), reference)
    labels = output.get("Labels") if isinstance(output.get("Labels"), dict) else {}
    label_base = labels.get("org.tunaos.live-overlay.base-digest")
    if not label_base:
        raise RuntimeError(f"{reference}: missing base digest label")
    if label_base != base_digest:
        raise RuntimeError(f"{reference}: base digest moved from {base_digest} to {label_base}")
    return {
        "variant": variant,
        "flavor": flavor,
        "platform": platform,
        "liveOverlayDigest": digest,
        "liveOverlayBaseDigest": label_base,
    }


def _engine_pin() -> str:
    versions = yaml.safe_load(VERSIONS.read_text(encoding="utf-8"))
    downloads = versions.get("downloads") if isinstance(versions, dict) else None
    pin = downloads.get("tacklebox") if isinstance(downloads, dict) else None
    if not isinstance(pin, str) or not pin:
        raise RuntimeError("image-versions.yaml has no downloads.tacklebox pin")
    return "sha256:" + hashlib.sha256(f"tacklebox:{pin}".encode()).hexdigest()


def collect(
    config: dict[str, Any],
    wanted_variant: str = "",
    wanted_flavor: str = "",
    wanted_platform: str = "",
) -> dict[str, Any]:
    descriptors: dict[str, Any] = {}
    overlays: dict[str, Any] = {}
    for variant_cfg in config.get("variants", []):
        if not isinstance(variant_cfg, dict):
            continue
        variant = variant_cfg.get("id")
        if not isinstance(variant, str) or (wanted_variant and variant != wanted_variant):
            continue
        for flavor_cfg in variant_cfg.get("flavors", []):
            if (not isinstance(flavor_cfg, dict)
                    or flavor_cfg.get("build_image") is not True):
                continue
            flavor = flavor_cfg.get("id")
            if (not isinstance(flavor, str)
                    or (wanted_flavor and flavor != wanted_flavor)):
                continue
            platforms = flavor_cfg.get("platforms") or variant_cfg.get("platforms") or ["linux/amd64"]
            for platform in platforms:
                if wanted_platform and platform != wanted_platform:
                    continue
                key = f"{variant}:{flavor}:{platform}"
                try:
                    identity = _image_identity(config, variant, flavor, platform)
                except RuntimeError as exc:
                    print(f"::warning::{key}: {exc}", file=sys.stderr)
                    continue
                descriptors[key] = identity
                if not OVERLAY_FLAVOR.fullmatch(flavor):
                    continue
                try:
                    overlays[key] = _overlay_identity(
                        variant, flavor, platform, identity["platformManifestDigest"]
                    )
                except RuntimeError as exc:
                    print(f"::warning::{key}: {exc}", file=sys.stderr)
    return {
        "currentInputs": {
            "descriptors": descriptors,
            "overlays": overlays,
            "pins": {"engineRevision": _engine_pin()},
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", default="")
    parser.add_argument("--flavor", default="")
    parser.add_argument("--platform", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = tunaos_config.matrix(tunaos_config.load())
        document = collect(config, args.variant, args.flavor, args.platform)
        args.output.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, RuntimeError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"::error::current delivery inputs unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
