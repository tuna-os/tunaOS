"""Resolve support commitments independently from scheduled build restrictions.

The runtime matrix narrows PR jobs and several flavors while supply is missing.
Those restrictions cannot remove targets from the required coverage denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

PLATFORMS = {
    "linux/amd64": ("linux", "amd64", None, "x86-64"),
    "linux/amd64/v2": ("linux", "amd64", "v2", "x86-64-v2"),
    "linux/arm64": ("linux", "arm64", None, "armv8-a"),
}
ALMA_VARIANTS = frozenset({"albacore", "yellowfin"})
# Native EL10/ELN support requires v3 even when OCI architecture is amd64.
# https://www.centos.org/centos10/ documents the Stream 10 requirement.
# ELN compiler policy: fedora-eln/eln-docs, modules/ROOT/pages/buildroot.adoc.
NATIVE_V3_VARIANTS = frozenset({"skipjack", "wahoo"})
IDENTIFIER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def split_platform(platform: str) -> tuple[str, str, str | None]:
    """Return OCI os, architecture and variant without conflating v2 with arch."""
    if not isinstance(platform, str) or platform not in PLATFORMS:
        raise ValueError(f"unsupported platform: {platform!r}")
    return PLATFORMS[platform][:3]


def cpu_baseline(variant: str, platform: str) -> str:
    split_platform(platform)
    if platform == "linux/amd64" and variant in NATIVE_V3_VARIANTS:
        return "x86-64-v3"
    return PLATFORMS[platform][3]


def platform_slug(platform: str) -> str:
    split_platform(platform)
    return platform.replace("/", "-")


def package_architecture(platform: str, manager: str) -> str:
    """Package architecture does not prove CPU baseline compatibility."""
    _, architecture, _ = split_platform(platform)
    if manager in {"dnf", "zypper", "rpm"}:
        return {"amd64": "x86_64", "arm64": "aarch64"}[architecture]
    if manager in {"apt", "dpkg"}:
        return architecture
    if manager in {"pacman", "portage"}:
        return {"amd64": "x86_64", "arm64": "aarch64"}[architecture]
    raise ValueError(f"unsupported package manager: {manager!r}")


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def _platforms(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a nonempty platform list")
    for platform in value:
        split_platform(platform)
    if len(set(value)) != len(value):
        raise ValueError(f"duplicate platforms in {field}")
    return value


def hardware_scope(flavor: str) -> str:
    tokens = _identifier(flavor, "flavor").split("-")
    if "asahi" in tokens and "t2" in tokens:
        raise ValueError("Asahi and T2 hardware scopes cannot be combined")
    if "asahi" in tokens:
        return "apple-silicon"
    if "t2" in tokens:
        return "apple-t2"
    return "generic"


def validate_target(target: dict[str, Any]) -> None:
    """Reject inconsistent hardware, baseline and full platform identities."""
    fields = {"variant", "flavor", "platform", "cpuBaseline", "hardwareScope"}
    if not isinstance(target, dict) or set(target) != fields:
        raise ValueError("target must contain the five canonical identity fields")
    variant = _identifier(target["variant"], "variant")
    scope = hardware_scope(target["flavor"])
    platform = target["platform"]
    split_platform(platform)
    if target["hardwareScope"] != scope:
        raise ValueError("hardware scope does not match flavor")
    if target["cpuBaseline"] != cpu_baseline(variant, platform):
        raise ValueError("CPU baseline does not match platform")
    if platform == "linux/amd64/v2" and variant not in ALMA_VARIANTS:
        raise ValueError("AMD64/v2 is restricted to Alma variants")
    if variant in ALMA_VARIANTS and platform == "linux/amd64":
        raise ValueError("Alma Intel targets must use AMD64/v2")
    if scope == "apple-silicon" and platform != "linux/arm64":
        raise ValueError("Asahi requires ARM64")
    if scope == "apple-t2" and platform == "linux/arm64":
        raise ValueError("T2 requires Intel")


def target_key(target: dict[str, Any]) -> str:
    validate_target(target)
    return ":".join(target[field] for field in ("variant", "flavor", "platform"))


def configured_platforms(variant: dict, flavor: dict) -> list[str]:
    """Match runtime jq's flavor // variant inheritance, including null."""
    value = flavor.get("platforms")
    if value is None:
        value = variant.get("platforms")
    return _platforms(value, f"scheduled {variant['id']}:{flavor['id']}")


def resolve_required_targets(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve enabled flavors and annotate whether each commitment is scheduled.

    Policy is authored separately from scheduler platforms. Fixed defaults keep
    older configuration readable; explicit policy cannot weaken accepted support.
    """
    if not isinstance(config, dict) or not isinstance(config.get("variants"), list):
        raise ValueError("configuration requires a variants list")
    global_policy = config.get("config", {}).get(
        "required_platforms", ["linux/amd64", "linux/arm64"]
    )
    if set(_platforms(global_policy, "global required_platforms")) != {
        "linux/amd64", "linux/arm64"
    }:
        raise ValueError("ordinary variants require AMD64 and ARM64")
    records = []
    seen_variants = set()
    for variant in config["variants"]:
        variant_id = _identifier(variant.get("id"), "variant")
        if variant_id in seen_variants:
            raise ValueError(f"duplicate variant: {variant_id}")
        seen_variants.add(variant_id)
        policy = (
            ["linux/amd64/v2", "linux/arm64"]
            if variant_id in ALMA_VARIANTS else global_policy
        )
        declared = variant.get("required_platforms", policy)
        if set(_platforms(declared, f"required {variant_id}")) != set(policy):
            raise ValueError(f"required policy contradicts supported targets: {variant_id}")
        publication_name = _identifier(variant.get("publish_name", variant_id), "publication name")
        suffix = variant.get("tag_suffix", "")
        if suffix:
            _identifier(suffix, "tag suffix")
        flavors = variant.get("flavors")
        if not isinstance(flavors, list):
            raise ValueError(f"flavors must be a list: {variant_id}")
        seen_flavors = set()
        for flavor in flavors:
            flavor_id = _identifier(flavor.get("id"), "flavor")
            if flavor_id in seen_flavors:
                raise ValueError(f"duplicate flavor: {variant_id}:{flavor_id}")
            seen_flavors.add(flavor_id)
            enabled = flavor.get("build_image", False)
            if not isinstance(enabled, bool):
                raise ValueError(f"build_image must be boolean: {variant_id}:{flavor_id}")
            if not enabled:
                continue
            scheduled = configured_platforms(variant, flavor)
            scope = hardware_scope(flavor_id)
            required = [p for p in policy if (
                (scope != "apple-silicon" or p == "linux/arm64")
                and (scope != "apple-t2" or p != "linux/arm64")
            )]
            for platform in required:
                target = {
                    "variant": variant_id,
                    "flavor": flavor_id,
                    "platform": platform,
                    "cpuBaseline": cpu_baseline(variant_id, platform),
                    "hardwareScope": scope,
                }
                validate_target(target)
                records.append({
                    "target": target,
                    "required": True,
                    "scheduled": platform in scheduled,
                    "publication": {
                        "repository": f"ghcr.io/tuna-os/{publication_name}",
                        "tag": f"{flavor_id}-{suffix}" if suffix else flavor_id,
                    },
                })
    records.sort(key=lambda record: target_key(record["target"]))
    return records


def coverage_document(config: dict[str, Any]) -> dict[str, Any]:
    records = resolve_required_targets(config)
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schemaVersion": 1,
        "kind": "required-targets",
        "coverageDigest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        "targets": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(".github/build-config.yml"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    document = coverage_document(yaml.safe_load(args.config.read_text()))
    body = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(body)
    else:
        print(body, end="")


if __name__ == "__main__":
    main()
