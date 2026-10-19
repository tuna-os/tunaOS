#!/usr/bin/env python3
"""Per-target delivery cutover gate for R2 ISO uploads and retention pruning.

The policy file (.github/delivery-cutover.json) records which {variant,
flavor, platform} targets have qualified for delivery cutover and which R2
objects must be retained afterwards. Workflows consult this script:

- target gate:  --check --variant V --flavor F --platform P
- group gate:   --check --variant V --group SUFFIX
- prune filter: --retained
- matrix gate:  --annotate-matrix < matrix.json

With the EMPTY initial policy every gate evaluates to today's behavior:
is_cut_over() is False for all targets, group_covered() is False for all
groups, retained_inventory() is empty. Uploads proceed and prune deletes
exactly as today. Nothing here performs R2 operations, builds, or workflow
runs; it only reads the policy and build-config data files.

Identity and receipt binding reuse scripts/contracts/targets.py: target_key()
for canonical identity, resolve_required_targets()/coverage_document() for
current-catalog membership, receipt_to_catalog_projection() for evidence
normalization, and downgrade_stale_targets() when a catalog snapshot is
supplied for full staleness verification.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import yaml
from contracts.targets import (
    DIGEST,
    coverage_document,
    cpu_baseline,
    downgrade_stale_targets,
    hardware_scope,
    receipt_to_catalog_projection,
    resolve_required_targets,
    target_key,
)

POLICY_SCHEMA_VERSION = 1
POLICY_KIND = "delivery-cutover"

DEFAULT_POLICY = REPO_ROOT / ".github" / "delivery-cutover.json"
DEFAULT_CONFIG = REPO_ROOT / ".github" / "build-config.yml"


def load_policy(path: str | Path = DEFAULT_POLICY) -> dict:
    """Load and minimally validate a DeliveryPolicy v1 document."""
    with open(path, "r", encoding="utf-8") as handle:
        policy = json.load(handle)
    if not isinstance(policy, dict):
        raise ValueError(f"policy must be a mapping: {path}")
    if policy.get("schemaVersion") != POLICY_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported policy schemaVersion: {policy.get('schemaVersion')!r}"
        )
    if policy.get("kind") != POLICY_KIND:
        raise ValueError(f"unsupported policy kind: {policy.get('kind')!r}")
    if not isinstance(policy.get("cutover", []), list):
        raise ValueError("policy 'cutover' must be a list")
    if not isinstance(policy.get("retained", []), list):
        raise ValueError("policy 'retained' must be a list")
    return policy


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict:
    """Load the build configuration that defines the current target catalog."""
    with open(path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"build config must be a mapping: {path}")
    return config
def load_current_inputs(path: str | Path | None):
    """Load observations collected independently of the qualification snapshot."""
    if not path:
        return None, None, None
    with open(path, "r", encoding="utf-8") as handle:
        current = json.load(handle)
    if not isinstance(current, dict):
        raise ValueError(f"current inputs must be a mapping: {path}")
    return current.get("descriptors"), current.get("overlays"), current.get("pins")


def canonical_target(variant: str, flavor: str, platform: str) -> dict[str, str]:
    """Build the five-field canonical target identity contracts.targets uses."""
    scope = hardware_scope(flavor)
    return {
        "variant": variant,
        "flavor": flavor,
        "platform": platform,
        "cpuBaseline": cpu_baseline(variant, platform),
        "hardwareScope": scope,
    }


def _cutover_entries(policy: dict) -> list[dict]:
    entries = policy.get("cutover", [])
    return [entry for entry in entries if isinstance(entry, dict)]


def find_entry(
    policy: dict, variant: str, flavor: str, platform: str
) -> dict | None:
    """Return the cutover entry for a target, or None when not cut over."""
    try:
        want = target_key(canonical_target(variant, flavor, platform))
    except ValueError:
        return None
    for entry in _cutover_entries(policy):
        target = entry.get("target")
        if not isinstance(target, dict):
            continue
        try:
            got = target_key(
                canonical_target(
                    target.get("variant", ""),
                    target.get("flavor", ""),
                    target.get("platform", ""),
                )
            )
        except ValueError:
            continue
        if got == want:
            return entry
    return None


def _evidence_binds(entry: dict, variant: str, flavor: str, platform: str) -> bool:
    """Check the entry's evidence is digest-bound to this target.

    Mirrors the digest binding downgrade_stale_targets enforces: the recorded
    receiptDigest must survive normalization via receipt_to_catalog_projection
    and stay attached to the same target identity.
    """
    evidence = entry.get("evidence")
    if not isinstance(evidence, dict):
        return False
    receipt_digest = evidence.get("receiptDigest")
    if not isinstance(receipt_digest, str) or not DIGEST.fullmatch(receipt_digest):
        return False
    qualified_at = evidence.get("qualifiedAt")
    if not isinstance(qualified_at, str) or not qualified_at:
        return False
    projected = receipt_to_catalog_projection(
        {
            "target": canonical_target(variant, flavor, platform),
            "receiptDigest": receipt_digest,
            "qualifiedAt": qualified_at,
        }
    )
    if projected.get("receiptDigest") != receipt_digest:
        return False
    try:
        projected_key = target_key(projected["target"])
    except (KeyError, ValueError):
        return False
    return projected_key == target_key(
        canonical_target(variant, flavor, platform)
    )


def catalog_target_keys(config: dict) -> set[str]:
    """Canonical keys of every required target in the current catalog."""
    coverage_document(config)  # Fail loudly on an inconsistent catalog.
    return {
        target_key(record["target"]) for record in resolve_required_targets(config)
    }


def is_cut_over(
    policy: dict,
    variant: str,
    flavor: str,
    platform: str,
    config: dict | None = None,
    snapshot: dict | None = None,
    current_descriptors=None,
    current_overlays=None,
    current_pins: dict | None = None,
) -> bool:
    """True only when the target entry is present and its evidence still holds.

    A snapshot is useful only with the observations that are current at the
    time of this check. If the caller cannot provide those observations, this
    returns False rather than treating an old qualified snapshot as fresh.
    """
    entry = find_entry(policy, variant, flavor, platform)
    if snapshot is None or entry is None:
        return False
    if not _evidence_binds(entry, variant, flavor, platform):
        return False
    if config is None:
        config = load_config()
    try:
        known = catalog_target_keys(config)
    except ValueError:
        return False
    try:
        key = target_key(canonical_target(variant, flavor, platform))
    except ValueError:
        return False
    if key not in known:
        return False

    if current_descriptors is None or current_overlays is None or current_pins is None:
        return False
    try:
        downgraded = downgrade_stale_targets(
            snapshot,
            current_descriptors=current_descriptors,
            current_overlays=current_overlays,
            current_pins=current_pins,
        )
    except ValueError:
        return False
    for catalog_entry in downgraded.get("targets", []):
        if catalog_entry.get("targetKey") != key:
            continue
        qualification = catalog_entry.get("qualification", {})
        if qualification.get("status") not in {"qualified", "local-only"}:
            return False
        return (
            qualification.get("receiptDigest")
            == entry.get("evidence", {}).get("receiptDigest")
        )
    return False


def group_members(
    config: dict, variant: str, suffix: str
) -> tuple[list[str], list[str]]:
    """Resolve a group's LIVE + OFFLINE member flavors for a variant.

    Mirrors scripts/build-iso-group.sh: each list is intersected with the
    variant's actual `build_image: true` flavors, preserving group order, with
    offline_flavors falling back to flavors when absent.
    """
    normalized = "" if suffix in ("", "default", "flagship") else suffix
    groups = config.get("iso_groups", [])
    if not isinstance(groups, list):
        raise ValueError("build config 'iso_groups' must be a list")
    group = None
    for candidate in groups:
        if isinstance(candidate, dict) and (candidate.get("suffix") or "") == normalized:
            group = candidate
            break
    if group is None:
        raise ValueError(f"no iso_group with suffix {suffix!r}")
    variant_flavors: list[str] = []
    for variant_entry in config.get("variants", []):
        if isinstance(variant_entry, dict) and variant_entry.get("id") == variant:
            for flavor in variant_entry.get("flavors", []):
                if isinstance(flavor, dict) and flavor.get("build_image") is True:
                    variant_flavors.append(flavor.get("id"))
            break
    if not variant_flavors:
        raise ValueError(f"unknown variant {variant!r}")
    live = [
        flavor
        for flavor in (group.get("flavors") or [])
        if flavor in variant_flavors
    ]
    offline_source = group.get("offline_flavors") or group.get("flavors") or []
    offline = [flavor for flavor in offline_source if flavor in variant_flavors]
    return live, offline


def required_platforms_for(
    config: dict, variant: str, flavor: str
) -> list[str]:
    """Required platforms for one flavor from the current catalog."""
    platforms: list[str] = []
    for record in resolve_required_targets(config):
        target = record["target"]
        if target["variant"] == variant and target["flavor"] == flavor:
            platforms.append(target["platform"])
    return sorted(set(platforms))


def group_covered(
    policy: dict,
    variant: str,
    suffix: str,
    live_members: list[str],
    offline_members: list[str],
    config: dict | None = None,
    snapshot: dict | None = None,
    current_descriptors=None,
    current_overlays=None,
    current_pins: dict | None = None,
) -> bool:
    """True only when every LIVE + OFFLINE member target is cut over."""
    if config is None:
        config = load_config()
    members = list(dict.fromkeys(list(live_members or []) + list(offline_members or [])))
    if not members:
        return False
    for flavor in members:
        try:
            platforms = required_platforms_for(config, variant, flavor)
        except ValueError:
            return False
        if not platforms:
            return False
        for platform in platforms:
            if not is_cut_over(
                policy,
                variant,
                flavor,
                platform,
                config=config,
                snapshot=snapshot,
                current_descriptors=current_descriptors,
                current_overlays=current_overlays,
                current_pins=current_pins,
            ):
                return False
    return True


def retained_inventory(policy: dict) -> list[str]:
    """Protected R2 object basenames that must survive retention pruning."""
    retained = policy.get("retained", [])
    names = [
        name for name in retained if isinstance(name, str) and name and "/" not in name
    ]
    return sorted(set(names))


def annotate_matrix(
    matrix: dict,
    policy: dict,
    config: dict,
    default_platform: str = "linux/amd64",
    snapshot: dict | None = None,
    current_descriptors=None,
    current_overlays=None,
    current_pins: dict | None = None,
) -> dict:
    """Add a per-row `cutover` boolean to a {variant, flavor, platform} matrix."""
    rows = matrix.get("include", [])
    if not isinstance(rows, list):
        raise ValueError("matrix must carry an 'include' list")
    annotated = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("matrix rows must be mappings")
        variant = row.get("variant", "")
        flavor = row.get("flavor", "")
        platform = row.get("platform", "") or default_platform
        annotated.append(
            {
                **row,
                "cutover": bool(
                    is_cut_over(
                        policy,
                        variant,
                        flavor,
                        platform,
                        config=config,
                        snapshot=snapshot,
                        current_descriptors=current_descriptors,
                        current_overlays=current_overlays,
                        current_pins=current_pins,
                    )
                ),
            }
        )
    return {"include": annotated}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--variant", default="")
    parser.add_argument("--flavor", default="")
    parser.add_argument("--platform", default="")
    parser.add_argument("--group", default="")
    parser.add_argument("--current-inputs", default="")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--retained", action="store_true")
    parser.add_argument("--annotate-matrix", action="store_true")
    parser.add_argument("--default-platform", default="linux/amd64")
    args = parser.parse_args(argv)

    if args.annotate_matrix:
        policy = load_policy(args.policy)
        config = load_config(args.config)
        snapshot = None
        if args.snapshot:
            with open(args.snapshot, "r", encoding="utf-8") as handle:
                snapshot = json.load(handle)
        current_descriptors, current_overlays, current_pins = load_current_inputs(
            args.current_inputs
        )
        matrix = json.load(sys.stdin)
        json.dump(
            annotate_matrix(
                matrix,
                policy,
                config,
                args.default_platform,
                snapshot=snapshot,
                current_descriptors=current_descriptors,
                current_overlays=current_overlays,
                current_pins=current_pins,
            ),
            sys.stdout,
        )
        sys.stdout.write("\n")
        return 0

    if args.retained:
        policy = load_policy(args.policy)
        for name in retained_inventory(policy):
            sys.stdout.write(f"- {name}\n")
        return 0

    if args.check:
        policy = load_policy(args.policy)
        config = load_config(args.config)
        snapshot = None
        if args.snapshot:
            with open(args.snapshot, "r", encoding="utf-8") as handle:
                snapshot = json.load(handle)
        current_descriptors, current_overlays, current_pins = load_current_inputs(
            args.current_inputs
        )
        if args.group:
            live, offline = group_members(config, args.variant, args.group)
            covered = group_covered(
                policy,
                args.variant,
                args.group,
                live,
                offline,
                config=config,
                snapshot=snapshot,
                current_descriptors=current_descriptors,
                current_overlays=current_overlays,
                current_pins=current_pins,
            )
            sys.stdout.write(("true" if covered else "false") + "\n")
            return 0 if covered else 1
        if args.variant and args.flavor and args.platform:
            cut = is_cut_over(
                policy,
                args.variant,
                args.flavor,
                args.platform,
                config=config,
                snapshot=snapshot,
                current_descriptors=current_descriptors,
                current_overlays=current_overlays,
                current_pins=current_pins,
            )
            sys.stdout.write(("true" if cut else "false") + "\n")
            return 0 if cut else 1
        parser.error("--check needs --variant/--flavor/--platform or --variant/--group")
        return 2

    parser.error("nothing to do: pass --check, --retained, or --annotate-matrix")
    return 2


if __name__ == "__main__":
    sys.exit(main())
