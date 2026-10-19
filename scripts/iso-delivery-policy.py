#!/usr/bin/env python3
"""Evaluate the reviewed ISO delivery cutover policy.

Workflows pass this program a JSON rendering of .github/build-config.yml. Keeping
policy decisions here makes the per-flavor publisher, grouped publisher, and R2
pruner use the same exact target and retention rules.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

QUALIFIED = "browser-qualified"
PLATFORM_ARCH = {
    "linux/amd64": "x86_64",
    "linux/arm64": "aarch64",
}
VERSION_COMPONENT = r"[0-9]+(?:[._+~-][A-Za-z0-9]+)*"


class PolicyError(ValueError):
    """The delivery policy is unsafe or refers to an unknown build target."""


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read config JSON {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise PolicyError("config JSON must be an object")
    return config


def policy_for(config: dict[str, Any]) -> dict[str, Any]:
    policy = config.get("iso_delivery", {})
    if not isinstance(policy, dict):
        raise PolicyError("iso_delivery must be an object")
    return policy


def variant_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    variants = config.get("variants", [])
    if not isinstance(variants, list):
        raise PolicyError("variants must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for variant in variants:
        if not isinstance(variant, dict) or not isinstance(variant.get("id"), str):
            raise PolicyError("every variant must have a string id")
        variant_id = variant["id"]
        if variant_id in indexed:
            raise PolicyError(f"duplicate variant {variant_id!r}")
        indexed[variant_id] = variant
    return indexed


def flavor_index(variant: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for flavor in variant.get("flavors", []):
        if not isinstance(flavor, dict) or not isinstance(flavor.get("id"), str):
            raise PolicyError(f"variant {variant['id']!r} has a flavor without an id")
        flavor_id = flavor["id"]
        if flavor_id in indexed:
            raise PolicyError(
                f"variant {variant['id']!r} has duplicate flavor {flavor_id!r}"
            )
        indexed[flavor_id] = flavor
    return indexed


def retained_isos(policy: dict[str, Any]) -> tuple[str, ...]:
    retained = policy.get("retained_r2_isos", [])
    if not isinstance(retained, list):
        raise PolicyError("iso_delivery.retained_r2_isos must be a list")
    checked: list[str] = []
    seen: set[str] = set()


    for name in retained:
        if not isinstance(name, str) or not name:
            raise PolicyError("every retained R2 ISO must be a non-empty string")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+~-]*\.iso", name):
            raise PolicyError(
                f"retained R2 ISO {name!r} must be a safe single-line basename"
            )
        if name in seen:
            raise PolicyError(f"duplicate retained R2 ISO {name!r}")
        seen.add(name)
        checked.append(name)
    return tuple(checked)


def latest_name(variant: str, flavor: str, platform: str) -> str:
    if platform == "linux/amd64":
        return f"{variant}-{flavor}-latest.iso"
    return f"{variant}-{flavor}-latest-{platform.rsplit('/', 1)[-1]}.iso"


def has_dated_iso(
    retained: tuple[str, ...], variant: str, flavor: str, platform: str
) -> bool:
    arch = PLATFORM_ARCH[platform]
    pattern = re.compile(
        rf"^{re.escape(variant)}-{re.escape(flavor)}-"
        rf"{VERSION_COMPONENT}-{re.escape(arch)}\.iso$"
    )
    return any(pattern.fullmatch(name) for name in retained)


def active_targets(config: dict[str, Any]) -> frozenset[tuple[str, str, str]]:
    policy = policy_for(config)
    targets = policy.get("cutover_targets", [])
    if not isinstance(targets, list):
        raise PolicyError("iso_delivery.cutover_targets must be a list")

    variants = variant_index(config)
    retained = retained_isos(policy)
    active: set[tuple[str, str, str]] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise PolicyError("every cutover target must be an object")
        required = ("variant", "flavor", "platform", "qualification", "qualified_at", "evidence")
        missing = [field for field in required if not target.get(field)]
        if missing:
            raise PolicyError(f"cutover target is missing {', '.join(missing)}: {target!r}")

        variant_id = target["variant"]
        flavor_id = target["flavor"]
        platform = target["platform"]
        if not all(isinstance(value, str) for value in (variant_id, flavor_id, platform)):
            raise PolicyError(f"cutover target identity must use strings: {target!r}")
        if target["qualification"] != QUALIFIED:
            raise PolicyError(
                f"{variant_id}:{flavor_id}/{platform} is not {QUALIFIED!r}"
            )
        try:
            date.fromisoformat(target["qualified_at"])
        except (TypeError, ValueError) as exc:
            raise PolicyError(
                f"{variant_id}:{flavor_id}/{platform} has an invalid qualified_at date"
            ) from exc
        if not isinstance(target["evidence"], str):
            raise PolicyError(
                f"{variant_id}:{flavor_id}/{platform} evidence must be a string"
            )

        variant = variants.get(variant_id)
        if variant is None:
            raise PolicyError(f"cutover target names unknown variant {variant_id!r}")
        flavor = flavor_index(variant).get(flavor_id)
        if flavor is None:
            raise PolicyError(
                f"cutover target names unknown flavor {variant_id}:{flavor_id}"
            )
        if flavor.get("build_image") is not True:
            raise PolicyError(f"cutover target {variant_id}:{flavor_id} is not built")
        platforms = flavor.get("platforms", variant.get("platforms", []))
        if platform not in platforms or platform not in PLATFORM_ARCH:
            raise PolicyError(
                f"cutover target {variant_id}:{flavor_id} does not build {platform}"
            )

        identity = (variant_id, flavor_id, platform)
        if identity in active:
            raise PolicyError(f"duplicate cutover target {variant_id}:{flavor_id}/{platform}")
        active.add(identity)

        if flavor.get("build_iso") is True:
            latest = latest_name(variant_id, flavor_id, platform)
            if latest not in retained:
                raise PolicyError(f"cutover target {identity!r} does not retain {latest!r}")
            if not has_dated_iso(retained, variant_id, flavor_id, platform):
                raise PolicyError(
                    f"cutover target {identity!r} has no retained versioned ISO"
                )

    validate_group_retention(config, active, retained)
    if active:
        raise PolicyError(
            "non-empty cutover_targets are disabled until #3381 supplies a "
            "current qualification catalog and matching receipt validation"
        )
    return frozenset(active)


def validate_group_retention(
    config: dict[str, Any],
    active: set[tuple[str, str, str]],
    retained: tuple[str, ...],
) -> None:
    groups = config.get("iso_groups", [])
    if not isinstance(groups, list):
        raise PolicyError("iso_groups must be a list")
    for variant_id, variant in variant_index(config).items():
        flavors = flavor_index(variant)
        built = {
            flavor_id
            for flavor_id, flavor in flavors.items()
            if flavor.get("build_image") is True
            and "linux/amd64" in flavor.get("platforms", variant.get("platforms", []))
        }
        for group in groups:
            if not isinstance(group, dict):
                raise PolicyError("every ISO group must be an object")
            live = [
                flavor
                for flavor in group.get("flavors", [])
                if flavor in built
            ]
            if not live:
                continue
            required = [
                flavor
                for flavor in group.get("offline_flavors", group.get("flavors", []))
                if flavor in built
            ]
            if not required or not all(
                (variant_id, flavor, "linux/amd64") in active for flavor in required
            ):
                continue
            suffix = group.get("suffix", "")
            basename = variant_id if not suffix else f"{variant_id}-{suffix}"
            latest = f"{basename}-latest.iso"
            if latest not in retained:
                raise PolicyError(
                    f"fully cut-over group {basename!r} does not retain {latest!r}"
                )
            pattern = re.compile(
                rf"^{re.escape(basename)}-{VERSION_COMPONENT}-x86_64\.iso$"
            )
            if not any(pattern.fullmatch(name) for name in retained):
                raise PolicyError(
                    f"fully cut-over group {basename!r} has no retained versioned ISO"
                )


def read_matrix() -> dict[str, Any]:
    try:
        matrix = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"matrix input is not JSON: {exc}") from exc
    if not isinstance(matrix, dict) or not isinstance(matrix.get("include"), list):
        raise PolicyError("matrix input must be an object with an include list")
    return matrix


def annotate_targets(
    config: dict[str, Any], active: frozenset[tuple[str, str, str]]
) -> None:
    matrix = read_matrix()
    for row in matrix["include"]:
        identity = (row.get("variant"), row.get("flavor"), row.get("platform"))
        row["r2_cutover"] = identity in active
    json.dump(matrix, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


def annotate_groups(
    config: dict[str, Any], active: frozenset[tuple[str, str, str]]
) -> None:
    del config
    matrix = read_matrix()
    for row in matrix["include"]:
        variant = row.get("variant")
        platform = row.get("platform", "linux/amd64")
        required = row.get("required_flavors", [])
        if not isinstance(required, list):
            raise PolicyError("group matrix required_flavors must be a list")
        row["r2_cutover"] = bool(required) and all(
            (variant, flavor, platform) in active for flavor in required
        )
    json.dump(matrix, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


def object_is_retained(config: dict[str, Any], object_name: str) -> bool:
    """Whether an exact R2 destination or either sidecar is immutable."""
    if object_name.endswith(".sha256"):
        object_name = object_name.removesuffix(".sha256")
    elif object_name.endswith(".sigstore.json"):
        object_name = object_name.removesuffix(".sigstore.json")
    return object_name in retained_isos(policy_for(config))


def print_retention_filters(config: dict[str, Any]) -> None:
    policy = policy_for(config)
    for iso in retained_isos(policy):
        print(f"- /{iso}")
        print(f"- /{iso}.sha256")
        print(f"- /{iso}.sigstore.json")
    # Stable pointers and their resolver stay immutable. Checksum snapshots use
    # "-snapshot-", so they remain eligible for age pruning.
    print("- *-latest.iso")
    print("- *-latest-*.iso")
    print("- *-latest.iso.sha256")
    print("- *-latest-*.iso.sha256")
    print("- *-latest.iso.sigstore.json")
    print("- *-latest-*.iso.sigstore.json")
    print("- *-latest.json")
    print("- *-latest-*.json")
    print("+ *.iso")
    print("+ *.iso.sha256")
    print("+ *.iso.sigstore.json")
    print("- *")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-json", type=Path, required=True)
    parser.add_argument(
        "command",
        choices=(
            "validate", "annotate-target-matrix", "annotate-group-matrix",
            "retention-filters", "object-protected",
        ),
    )
    parser.add_argument("--object")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config_json)
        active = active_targets(config)
        if args.command == "validate":
            print(f"ISO delivery policy valid: {len(active)} cutover target(s)")
        elif args.command == "annotate-target-matrix":
            annotate_targets(config, active)
        elif args.command == "annotate-group-matrix":
            annotate_groups(config, active)
        elif args.command == "retention-filters":
            print_retention_filters(config)
        else:
            if not args.object:
                raise PolicyError("object-protected requires --object")
            print("true" if object_is_retained(config, args.object) else "false")
    except PolicyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
