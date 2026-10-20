"""Resolve support commitments independently from scheduled build restrictions.

The runtime matrix narrows PR jobs and several flavors while supply is missing.
Those restrictions cannot remove targets from the required coverage denominator.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any


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

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
CATALOG_STATUSES = frozenset({"qualified", "local-only", "unqualified", "unsupported"})
INDEX_MEDIA_TYPES = frozenset({
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
})

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
    if (variant in ALMA_VARIANTS and platform == "linux/amd64"
            and "nvidia" not in target["flavor"].split("-")):
        raise ValueError("Alma Intel targets must use AMD64/v2 unless the flavor is x86_64-only")
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

    Scheduler `platforms` never narrows support. A flavor `required_platforms`
    declares a permanent compatibility limit; NVIDIA flavors default to their
    intrinsic x86_64-only limit when the declaration is absent.
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
            if scope == "apple-silicon" and any(p != "linux/arm64" for p in scheduled):
                raise ValueError(f"Asahi scheduler includes a non-ARM64 platform: {variant_id}:{flavor_id}")
            if scope == "apple-t2" and "linux/arm64" in scheduled:
                raise ValueError(f"T2 scheduler includes ARM64: {variant_id}:{flavor_id}")
            permanent = flavor.get("required_platforms")
            if permanent is None:
                if "nvidia" in flavor_id.split("-"):
                    permanent = ["linux/amd64"]
                elif scope == "apple-silicon":
                    permanent = ["linux/arm64"]
                elif scope == "apple-t2":
                    permanent = [platform for platform in policy if platform != "linux/arm64"]
                else:
                    permanent = policy
            required = _platforms(permanent, f"required {variant_id}:{flavor_id}")
            if scope == "apple-silicon" and required != ["linux/arm64"]:
                raise ValueError(f"Asahi support must be ARM64-only: {variant_id}:{flavor_id}")
            if scope == "apple-t2" and any(p == "linux/arm64" for p in required):
                raise ValueError(f"T2 support cannot include ARM64: {variant_id}:{flavor_id}")
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



def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _optional_digest(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def _oci_platform(platform: str) -> dict[str, str | None]:
    os_name, architecture, variant = split_platform(platform)
    return {
        "os": os_name,
        "architecture": architecture,
        "variant": variant,
    }


def _descriptor_matches_platform(desc: dict[str, Any], platform: str) -> bool:
    expected_os, expected_arch, expected_variant = split_platform(platform)
    if isinstance(desc.get("target"), dict):
        if desc["target"].get("platform") != platform:
            return False
    if desc.get("platform") is not None:
        if desc["platform"] != platform:
            return False
    oci = desc.get("ociPlatform")
    if oci is not None:
        if not isinstance(oci, dict):
            raise ValueError("ociPlatform must be a mapping")
        obs_os = oci.get("os")
        obs_arch = oci.get("architecture")
        obs_var = oci.get("variant")
        if obs_os != expected_os or obs_arch != expected_arch:
            return False
        if expected_arch == "arm64" and expected_variant is None:
            if obs_var not in (None, "v8"):
                return False
        elif obs_var != expected_variant:
            return False
    return True


def _is_unsupported_target(target: dict[str, Any]) -> bool:
    flavor = target["flavor"]
    if target["hardwareScope"] in {"apple-silicon", "apple-t2"}:
        return True
    if flavor == "base" or flavor.startswith("base-"):
        return True
    return False


def _default_desktop(flavor: str) -> str:
    if flavor == "base" or flavor.startswith("base-"):
        return ""
    return flavor.split("-")[0]


def _normalize_repo(repository: str) -> str:
    if repository.startswith("ghcr.io/"):
        return repository
    if repository.startswith("tuna-os/"):
        return f"ghcr.io/{repository}"
    return f"ghcr.io/tuna-os/{repository}"


def _parse_ref_and_platform(key: str) -> tuple[str | None, str | None, str | None]:
    platform: str | None = None
    ref = key
    if "@" in key:
        ref, platform_part = key.rsplit("@", 1)
        if platform_part in PLATFORMS:
            platform = platform_part
        else:
            return None, None, None
    parts = ref.split(":")
    if len(parts) == 3 and parts[2] in PLATFORMS and "/" not in parts[0]:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], platform
    return None, None, None


def _index_descriptors(
    descriptors: Any,
    config: dict[str, Any],
    required_by_key: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if not descriptors:
        return {}, []

    variant_by_pub: dict[tuple[str, str], tuple[str, str, bool]] = {}
    variant_configs: dict[str, dict[str, Any]] = {}
    for variant in config.get("variants", []):
        vid = variant.get("id")
        if not isinstance(vid, str):
            continue
        variant_configs[vid] = variant
        pub_name = variant.get("publish_name", vid)
        suffix = variant.get("tag_suffix", "")
        repo = f"ghcr.io/tuna-os/{pub_name}"
        for flavor in variant.get("flavors", []):
            fid = flavor.get("id")
            if not isinstance(fid, str):
                continue
            tag = f"{fid}-{suffix}" if suffix else fid
            sched: list[str] = []
            try:
                sched = configured_platforms(variant, flavor)
            except ValueError:
                sched = []
            for plat in PLATFORMS:
                variant_by_pub[(f"{repo}:{tag}", plat)] = (vid, fid, plat in sched)

    raw_items: list[tuple[Any, dict[str, Any]]] = []
    if isinstance(descriptors, dict):
        for key, value in descriptors.items():
            if value is None:
                continue
            if not isinstance(value, dict):
                raise ValueError(f"descriptor for {key!r} must be a mapping")
            if isinstance(value.get("platforms"), dict):
                for plat_key, plat_val in value["platforms"].items():
                    if isinstance(plat_val, dict):
                        merged = {k: v for k, v in value.items() if k != "platforms"}
                        merged.update(plat_val)
                        merged.setdefault("platform", plat_key)
                        raw_items.append((key, merged))
            else:
                raw_items.append((key, dict(value)))
    elif isinstance(descriptors, list):
        for item in descriptors:
            if not isinstance(item, dict):
                raise ValueError("descriptor list items must be mappings")
            raw_items.append((None, dict(item)))
    else:
        raise ValueError("descriptors must be a mapping or list")

    by_target_key: dict[str, dict[str, Any]] = {}
    extra_records: list[dict[str, Any]] = []

    for key, desc in raw_items:
        target_obj = desc.get("target")
        variant_id: str | None = desc.get("variant")
        flavor_id: str | None = desc.get("flavor")
        platform: str | None = desc.get("platform")
        repository: str | None = desc.get("repository")
        tag: str | None = desc.get("tag")

        if isinstance(desc.get("publication"), dict):
            repository = repository or desc["publication"].get("repository")
            tag = tag or desc["publication"].get("tag")

        if isinstance(key, tuple):
            if len(key) == 3:
                k0, k1, k2 = key
                if isinstance(k0, str) and ("/" in k0 or k0.startswith("ghcr.io")):
                    repository = repository or _normalize_repo(k0)
                    tag = tag or k1
                    platform = platform or k2
                else:
                    variant_id = variant_id or k0
                    flavor_id = flavor_id or k1
                    platform = platform or k2
            elif len(key) == 2:
                k0, k1 = key
                if isinstance(k0, str) and ("/" in k0 or k0.startswith("ghcr.io")):
                    repository = repository or _normalize_repo(k0)
                    tag = tag or k1
                else:
                    variant_id = variant_id or k0
                    flavor_id = flavor_id or k1
        elif isinstance(key, str):
            if key in required_by_key:
                req_rec = required_by_key[key]
                req_target = req_rec["target"]
                if not _descriptor_matches_platform(desc, req_target["platform"]):
                    continue
                by_target_key[key] = desc
                continue
            p0, p1, p2 = _parse_ref_and_platform(key)
            if p0 is not None and p1 is not None:
                if "/" in p0:
                    repository = repository or _normalize_repo(p0)
                    tag = tag or p1
                else:
                    variant_id = variant_id or p0
                    flavor_id = flavor_id or p1
                if p2 is not None and platform is None:
                    platform = p2

        if platform is None and isinstance(desc.get("ociPlatform"), dict):
            oci = desc["ociPlatform"]
            os_n, arch_n, var_n = oci.get("os"), oci.get("architecture"), oci.get("variant")
            if os_n == "linux" and arch_n == "amd64" and var_n == "v2":
                platform = "linux/amd64/v2"
            elif os_n == "linux" and arch_n == "amd64" and var_n is None:
                platform = "linux/amd64"
            elif os_n == "linux" and arch_n == "arm64" and var_n in (None, "v8"):
                platform = "linux/arm64"

        if isinstance(target_obj, dict):
            validate_target(target_obj)
            tkey = target_key(target_obj)
            if not _descriptor_matches_platform(desc, target_obj["platform"]):
                continue
            by_target_key[tkey] = desc
            if tkey not in required_by_key:
                v_cfg = variant_configs.get(target_obj["variant"], {})
                pub_name = _identifier(v_cfg.get("publish_name", target_obj["variant"]), "publication name")
                suffix = v_cfg.get("tag_suffix", "")
                extra_records.append({
                    "target": dict(target_obj),
                    "required": bool(desc.get("required", False)),
                    "scheduled": bool(desc.get("scheduled", False)),
                    "publication": {
                        "repository": repository or f"ghcr.io/tuna-os/{pub_name}",
                        "tag": tag or (f"{target_obj['flavor']}-{suffix}" if suffix else target_obj["flavor"]),
                    },
                })
            continue

        if platform is None:
            continue
        split_platform(platform)

        if repository and tag and (variant_id is None or flavor_id is None):
            norm_repo = _normalize_repo(repository)
            pub_match = variant_by_pub.get((f"{norm_repo}:{tag}", platform))
            if pub_match is not None:
                variant_id, flavor_id, _ = pub_match
            else:
                repo_tail = norm_repo.rsplit("/", 1)[-1]
                variant_id = variant_id or repo_tail
                flavor_id = flavor_id or tag

        if variant_id and flavor_id:
            candidate_key = f"{variant_id}:{flavor_id}:{platform}"
            if candidate_key in required_by_key:
                if not _descriptor_matches_platform(desc, platform):
                    continue
                by_target_key[candidate_key] = desc
                continue
            try:
                scope = hardware_scope(flavor_id)
                candidate_target = {
                    "variant": _identifier(variant_id, "variant"),
                    "flavor": _identifier(flavor_id, "flavor"),
                    "platform": platform,
                    "cpuBaseline": cpu_baseline(variant_id, platform),
                    "hardwareScope": scope,
                }
                validate_target(candidate_target)
            except ValueError:
                continue
            if not _descriptor_matches_platform(desc, platform):
                continue
            tkey = target_key(candidate_target)
            by_target_key[tkey] = desc
            v_cfg = variant_configs.get(variant_id, {})
            pub_name = _identifier(v_cfg.get("publish_name", variant_id), "publication name")
            suffix = v_cfg.get("tag_suffix", "")
            norm_repo = _normalize_repo(repository) if repository else f"ghcr.io/tuna-os/{pub_name}"
            norm_tag = tag or (f"{flavor_id}-{suffix}" if suffix else flavor_id)
            sched_flag = variant_by_pub.get((f"{norm_repo}:{norm_tag}", platform), (None, None, False))[2]
            extra_records.append({
                "target": candidate_target,
                "required": bool(desc.get("required", False)),
                "scheduled": bool(desc.get("scheduled", sched_flag)),
                "publication": {
                    "repository": norm_repo,
                    "tag": norm_tag,
                },
            })

    return by_target_key, extra_records


def _resolve_descriptor_digests(desc: dict[str, Any] | None) -> tuple[str | None, str | None, str | None]:
    """Return (indexDigest, platformManifestDigest, configDigest) for a descriptor."""
    if desc is None:
        return None, None, None
    res_in = desc.get("resolvedInputs") if isinstance(desc.get("resolvedInputs"), dict) else {}
    idx_digest = _optional_digest(
        desc.get("indexDigest") or res_in.get("indexDigest"),
        "indexDigest",
    )
    raw_pm = (
        desc.get("platformManifestDigest")
        or res_in.get("platformManifestDigest")
        or desc.get("childDigest")
        or desc.get("manifestDigest")
    )
    if raw_pm is None and desc.get("digest") is not None:
        if desc.get("mediaType") in INDEX_MEDIA_TYPES:
            idx_digest = idx_digest or _optional_digest(desc["digest"], "indexDigest")
        else:
            raw_pm = desc["digest"]
    pm_digest = _optional_digest(raw_pm, "platformManifestDigest")
    if pm_digest is not None and idx_digest is not None and pm_digest == idx_digest:
        raise ValueError("platformManifestDigest cannot be conflated with indexDigest")
    cfg_digest = _optional_digest(
        desc.get("configDigest") or res_in.get("configDigest"),
        "configDigest",
    )
    return idx_digest, pm_digest, cfg_digest


def _lookup_overlay(overlays: Any, target: dict[str, Any], publication: dict[str, str], desc: dict[str, Any] | None) -> tuple[bool, str | None, str | None, bool]:
    """Return (overlay_found, liveOverlayDigest, liveOverlayBaseDigest, conflicting_labels)."""
    tkey = target_key(target)
    variant = target["variant"]
    flavor = target["flavor"]
    platform = target["platform"]
    repo = publication["repository"]
    tag = publication["tag"]
    short_repo = repo.removeprefix("ghcr.io/")
    overlay_ref = f"ghcr.io/tuna-os/live-overlay:{variant}-{flavor}"
    short_overlay_ref = f"tuna-os/live-overlay:{variant}-{flavor}"

    candidate: dict[str, Any] | None = None
    if isinstance(overlays, dict):
        for probe in (
            tkey,
            (variant, flavor, platform),
            (repo, tag, platform),
            (short_repo, tag, platform),
            f"{repo}:{tag}@{platform}",
            f"{short_repo}:{tag}@{platform}",
            f"{overlay_ref}@{platform}",
            f"{short_overlay_ref}@{platform}",
            (variant, flavor),
            f"{variant}:{flavor}",
            f"{variant}-{flavor}",
            overlay_ref,
            short_overlay_ref,
            f"{repo}:{tag}",
            f"{short_repo}:{tag}",
        ):
            if probe in overlays and overlays[probe] is not None:
                val = overlays[probe]
                if not isinstance(val, dict):
                    raise ValueError(f"overlay for {probe!r} must be a mapping")
                if val.get("platform") is not None and val["platform"] != platform:
                    continue
                candidate = val
                break
    elif isinstance(overlays, list):
        for item in overlays:
            if not isinstance(item, dict):
                raise ValueError("overlay list items must be mappings")
            if isinstance(item.get("target"), dict) and target_key(item["target"]) == tkey:
                candidate = item
                break
            if (
                item.get("variant") == variant
                and item.get("flavor") == flavor
                and item.get("platform") in (None, platform)
            ):
                candidate = item
                break

    if candidate is None and isinstance(desc, dict):
        if isinstance(desc.get("overlay"), dict):
            candidate = desc["overlay"]
        elif any(k in desc for k in ("liveOverlayDigest", "liveOverlayBaseDigest", "overlayLabels")):
            candidate = desc

    if candidate is None:
        return False, None, None, False

    ovl_digest = _optional_digest(
        candidate.get("liveOverlayDigest")
        or candidate.get("platformManifestDigest")
        or candidate.get("manifestDigest")
        or candidate.get("digest"),
        "liveOverlayDigest",
    )
    labels = candidate.get("labels") or candidate.get("overlayLabels") or {}
    if not isinstance(labels, dict):
        raise ValueError("overlay labels must be a mapping")
    actual_label = _optional_digest(
        labels.get("org.tunaos.live-overlay.actual-base-digest") or candidate.get("actualBaseDigest"),
        "org.tunaos.live-overlay.actual-base-digest",
    )
    declared_label = _optional_digest(
        labels.get("org.tunaos.live-overlay.base-digest") or candidate.get("baseDigest"),
        "org.tunaos.live-overlay.base-digest",
    )
    direct_base = _optional_digest(candidate.get("liveOverlayBaseDigest"), "liveOverlayBaseDigest")

    conflicting = False
    if actual_label and declared_label and actual_label != declared_label:
        conflicting = True
    base_digest = direct_base or actual_label or declared_label
    if direct_base and actual_label and direct_base != actual_label:
        conflicting = True
    if direct_base and declared_label and direct_base != declared_label:
        conflicting = True

    return True, ovl_digest, base_digest, conflicting


def _match_receipt(
    receipts: Any,
    target: dict[str, Any],
    publication: dict[str, str],
    pm_digest: str,
    ovl_digest: str | None,
) -> tuple[dict[str, Any] | None, bool]:
    """Return (matching_receipt, saw_stale_receipt)."""
    if not receipts:
        return None, False

    tkey = target_key(target)
    repo = publication["repository"]
    tag = publication["tag"]
    short_repo = repo.removeprefix("ghcr.io/")
    platform = target["platform"]

    candidates: list[dict[str, Any]] = []
    if isinstance(receipts, dict):
        for probe in (
            tkey,
            (target["variant"], target["flavor"], platform),
            (repo, tag, platform),
            (short_repo, tag, platform),
            f"{repo}:{tag}@{platform}",
            f"{short_repo}:{tag}@{platform}",
            f"{repo}:{tag}",
            f"{short_repo}:{tag}",
        ):
            if probe in receipts and receipts[probe] is not None:
                val = receipts[probe]
                if isinstance(val, list):
                    candidates.extend(x for x in val if isinstance(x, dict))
                elif isinstance(val, dict):
                    candidates.append(val)
    elif isinstance(receipts, list):
        for item in receipts:
            if isinstance(item, dict):
                candidates.append(item)
    else:
        raise ValueError("receipts must be a mapping or list")

    saw_stale = False
    for receipt in candidates:
        if isinstance(receipt.get("target"), dict):
            try:
                if target_key(receipt["target"]) != tkey:
                    continue
            except ValueError:
                continue
        elif any(k in receipt for k in ("variant", "flavor", "platform")):
            if (
                receipt.get("variant", target["variant"]) != target["variant"]
                or receipt.get("flavor", target["flavor"]) != target["flavor"]
                or receipt.get("platform", platform) != platform
            ):
                continue

        res_inputs = receipt.get("resolvedInputs") if isinstance(receipt.get("resolvedInputs"), dict) else {}
        pub_info = receipt.get("publication") if isinstance(receipt.get("publication"), dict) else {}
        rec_pm_digest = _optional_digest(
            receipt.get("platformManifestDigest")
            or res_inputs.get("platformManifestDigest")
            or receipt.get("imageDigest")
            or receipt.get("manifestDigest")
            or pub_info.get("digest")
            or receipt.get("digest"),
            "receipt platformManifestDigest",
        )
        rec_ovl_digest = _optional_digest(
            receipt.get("liveOverlayDigest")
            or res_inputs.get("liveOverlayDigest")
            or receipt.get("overlayDigest"),
            "receipt liveOverlayDigest",
        )
        if rec_pm_digest != pm_digest:
            saw_stale = True
            continue
        if ovl_digest is not None and rec_ovl_digest is not None and rec_ovl_digest != ovl_digest:
            saw_stale = True
            continue
        if ovl_digest is None and rec_ovl_digest is not None:
            saw_stale = True
            continue
        return receipt, saw_stale

    return None, saw_stale


def _receipt_lookup(receipt: dict[str, Any], *names: str) -> Any:
    """First present value across top-level and nested input spellings."""
    sources = [receipt]
    for key in ("resolvedInputs", "resolved_inputs"):
        nested = receipt.get(key)
        if isinstance(nested, dict):
            sources.append(nested)
    for source in sources:
        for name in names:
            if source.get(name) not in (None, ""):
                return source[name]
    return None


def receipt_to_catalog_projection(receipt: dict[str, Any]) -> dict[str, Any]:
    """Project a QualificationEvidence/v1 receipt onto catalog_snapshot's receipts shape.

    Only normalizes field spellings (snake_case v1 evidence onto the camelCase
    shape _match_receipt and the qualification ladder read). Digest binding is
    unchanged: every digest still passes _optional_digest and matching still
    requires equality, never similarity.
    """
    if not isinstance(receipt, dict):
        raise ValueError("qualification receipt must be a mapping")

    projected: dict[str, Any] = {}
    for key in (
        "target", "variant", "flavor", "platform", "publication",
        "browser", "resources", "measurements", "evidence",
        "reason", "checks", "status", "localOnly",
        "imageDigest", "manifestDigest", "digest", "overlayDigest",
        "contractDigest",
    ):
        if key in receipt:
            projected[key] = receipt[key]
    if "localOnly" not in projected and "local_only" in receipt:
        projected["localOnly"] = receipt["local_only"]

    publication = receipt.get("publication") if isinstance(receipt.get("publication"), dict) else {}
    pm_raw = _receipt_lookup(
        receipt,
        "platformManifestDigest", "source", "imageDigest", "manifestDigest",
        "source_image_digest",
    )
    if pm_raw is None and publication.get("digest") not in (None, ""):
        pm_raw = publication["digest"]
    if pm_raw is None and receipt.get("digest") not in (None, ""):
        pm_raw = receipt["digest"]
    platform_manifest_digest = _optional_digest(pm_raw, "receipt platformManifestDigest") if pm_raw not in (None, "") else None
    live_overlay_digest = _optional_digest(
        _receipt_lookup(receipt, "liveOverlayDigest", "overlay", "overlayDigest"),
        "receipt liveOverlayDigest",
    )
    index_digest = _optional_digest(_receipt_lookup(receipt, "indexDigest"), "indexDigest")
    config_digest = _optional_digest(_receipt_lookup(receipt, "configDigest"), "configDigest")

    installer_revision = _receipt_lookup(receipt, "installerRevision", "installer_revision", "installer")
    installer_revision = str(installer_revision) if installer_revision not in (None, "") else ""
    engine_revision = _receipt_lookup(receipt, "engineRevision", "engine_revision", "engine")
    engine_revision = str(engine_revision) if engine_revision not in (None, "") else ""

    qualified_at = _receipt_lookup(
        receipt, "qualifiedAt", "qualified_at", "measuredAt", "measured_at", "generatedAt", "generated_at",
    )
    qualified_at = qualified_at if isinstance(qualified_at, str) and qualified_at else None
    receipt_digest_raw = _receipt_lookup(receipt, "receiptDigest", "receipt_digest", "contractDigest", "contract_digest")
    receipt_digest = _optional_digest(receipt_digest_raw, "receiptDigest") if receipt_digest_raw not in (None, "") else None

    status = projected.get("status")
    checks = projected.get("checks")
    checks_failed = isinstance(checks, list) and any(
        isinstance(c, dict) and c.get("status") not in (None, "pass", "passed", "success")
        for c in checks
    )
    if status is None and checks_failed:
        status = "fail"
    projected["status"] = status

    projected["platformManifestDigest"] = platform_manifest_digest
    projected["liveOverlayDigest"] = live_overlay_digest
    projected["indexDigest"] = index_digest
    projected["configDigest"] = config_digest
    projected["installerRevision"] = installer_revision
    projected["engineRevision"] = engine_revision
    projected["resolvedInputs"] = {
        "platformManifestDigest": platform_manifest_digest,
        "liveOverlayDigest": live_overlay_digest,
        "indexDigest": index_digest,
        "configDigest": config_digest,
        "installerRevision": installer_revision,
        "engineRevision": engine_revision,
    }
    projected["qualifiedAt"] = qualified_at
    projected["receiptDigest"] = receipt_digest
    return projected


def validate_catalog_entry(entry: dict[str, Any]) -> None:
    """Validate a single CatalogSnapshot target entry against schema and OCI invariants."""
    if not isinstance(entry, dict):
        raise ValueError("catalog entry must be a mapping")
    target = entry.get("target")
    if not isinstance(target, dict):
        raise ValueError("catalog entry requires target")
    validate_target(target)
    tkey = target_key(target)
    if entry.get("targetKey") is not None and entry["targetKey"] != tkey:
        raise ValueError("catalog entry targetKey disagrees with target")
    if not isinstance(entry.get("required"), bool) or not isinstance(entry.get("scheduled"), bool):
        raise ValueError("catalog entry required and scheduled must be boolean")

    pub = entry.get("publication")
    if not isinstance(pub, dict):
        raise ValueError("catalog entry requires publication mapping")
    repo = pub.get("repository")
    tag = pub.get("tag")
    if not isinstance(repo, str) or not repo or not isinstance(tag, str) or not tag:
        raise ValueError("catalog entry publication requires repository and tag")
    expected_ref = f"{repo}:{tag}"
    if pub.get("ref") is not None and pub["ref"] != expected_ref:
        raise ValueError("catalog entry publication ref disagrees with repository and tag")

    avail = entry.get("availability")
    if not isinstance(avail, dict) or not isinstance(avail.get("available"), bool):
        raise ValueError("catalog entry requires boolean availability.available")
    oci_plat = avail.get("ociPlatform")
    expected_oci = _oci_platform(target["platform"])
    if not isinstance(oci_plat, dict) or oci_plat != expected_oci:
        raise ValueError("catalog entry availability.ociPlatform disagrees with target platform")

    resolved = entry.get("resolvedInputs")
    if not isinstance(resolved, dict):
        raise ValueError("catalog entry requires resolvedInputs mapping")
    pm_digest = _optional_digest(resolved.get("platformManifestDigest"), "platformManifestDigest")
    idx_digest = _optional_digest(resolved.get("indexDigest"), "indexDigest")
    _optional_digest(resolved.get("configDigest"), "configDigest")
    ovl_digest = _optional_digest(resolved.get("liveOverlayDigest"), "liveOverlayDigest")
    ovl_base_digest = _optional_digest(resolved.get("liveOverlayBaseDigest"), "liveOverlayBaseDigest")

    if avail["available"] and pm_digest is None:
        raise ValueError("available catalog entry requires platformManifestDigest")
    if not avail["available"] and pm_digest is not None:
        raise ValueError("unavailable catalog entry cannot carry platformManifestDigest")
    if pm_digest is not None and idx_digest is not None and pm_digest == idx_digest:
        raise ValueError("platformManifestDigest cannot be conflated with indexDigest")

    facts = entry.get("facts")
    if not isinstance(facts, dict):
        raise ValueError("catalog entry requires facts mapping")
    if facts.get("digest") != pm_digest:
        raise ValueError("catalog entry facts.digest must match platformManifestDigest")
    if not isinstance(facts.get("hasSdBoot"), bool) or not isinstance(facts.get("bootc"), bool):
        raise ValueError("catalog entry facts boolean fields must be bool")
    for int_field in ("layerCount", "compressedSize"):
        val = facts.get(int_field)
        if type(val) is not int or val < 0:
            raise ValueError(f"catalog entry facts.{int_field} must be a non-negative integer")

    qual = entry.get("qualification")
    if not isinstance(qual, dict):
        raise ValueError("catalog entry requires qualification mapping")
    status = qual.get("status")
    if status not in CATALOG_STATUSES:
        raise ValueError(f"invalid qualification status: {status!r}")
    reason = qual.get("reason")
    if status == "qualified":
        if reason is not None:
            raise ValueError("qualified entry must not carry a blocker reason")
        if not avail["available"] or pm_digest is None:
            raise ValueError("qualified entry requires an available platformManifestDigest")
        if _is_unsupported_target(target):
            raise ValueError("unsupported target scope cannot be qualified")
        if ovl_base_digest is not None and ovl_base_digest != pm_digest:
            raise ValueError("qualified entry liveOverlayBaseDigest must match platformManifestDigest")
        if ovl_digest is not None and ovl_base_digest is None:
            raise ValueError("qualified entry with liveOverlayDigest requires liveOverlayBaseDigest")
        _optional_digest(qual.get("receiptDigest"), "receiptDigest")
        if qual.get("receiptDigest") is None:
            raise ValueError("qualified entry requires receiptDigest")
    else:
        if not isinstance(reason, str) or not reason:
            raise ValueError("non-qualified catalog entry requires a blocker reason")


def validate_catalog_snapshot(snapshot: dict[str, Any]) -> None:
    """Validate a complete CatalogSnapshot v1 document."""
    if not isinstance(snapshot, dict):
        raise ValueError("catalog snapshot must be a mapping")
    if snapshot.get("schemaVersion") != 1:
        raise ValueError(f"unsupported catalog snapshot schemaVersion: {snapshot.get('schemaVersion')!r}")
    if snapshot.get("kind") != "catalog-snapshot":
        raise ValueError(f"invalid catalog snapshot kind: {snapshot.get('kind')!r}")
    _optional_digest(snapshot.get("coverageDigest"), "coverageDigest")
    if snapshot.get("coverageDigest") is None:
        raise ValueError("catalog snapshot requires coverageDigest")
    snap_digest = _optional_digest(snapshot.get("snapshotDigest"), "snapshotDigest")
    if snap_digest is None:
        raise ValueError("catalog snapshot requires snapshotDigest")
    entries = snapshot.get("targets")
    if not isinstance(entries, list) or not entries:
        raise ValueError("catalog snapshot requires a non-empty targets list")
    keys: list[str] = []
    for entry in entries:
        validate_catalog_entry(entry)
        keys.append(target_key(entry["target"]))
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate target in catalog snapshot")
    if keys != sorted(keys):
        raise ValueError("catalog snapshot targets must be sorted by target_key")
    expected_digest = "sha256:" + hashlib.sha256(_canonical_json(entries)).hexdigest()
    if snap_digest != expected_digest:
        raise ValueError("catalog snapshotDigest does not match targets payload")


def catalog_snapshot(
    config: dict[str, Any],
    *,
    descriptors: Any = None,
    overlays: Any = None,
    receipts: Any = None,
    producer_revision: str = "",
    generated_at: str = "",
    installer_revision: str = "",
    engine_revision: str = "",
) -> dict[str, Any]:
    """Build and validate a canonical CatalogSnapshot v1 document."""
    coverage = coverage_document(config)
    required_records = coverage["targets"]
    required_by_key = {target_key(rec["target"]): rec for rec in required_records}
    desc_by_key, extra_records = _index_descriptors(descriptors, config, required_by_key)

    all_records = list(required_records)
    seen_keys = set(required_by_key)
    for extra in extra_records:
        tkey = target_key(extra["target"])
        if tkey not in seen_keys:
            seen_keys.add(tkey)
            all_records.append(extra)
    all_records.sort(key=lambda rec: target_key(rec["target"]))

    entries: list[dict[str, Any]] = []
    for record in all_records:
        target = record["target"]
        tkey = target_key(target)
        pub = record["publication"]
        repo = pub["repository"]
        tag = pub["tag"]
        ref = f"{repo}:{tag}"
        desc = desc_by_key.get(tkey)

        idx_digest, pm_digest, cfg_digest = _resolve_descriptor_digests(desc)

        available = pm_digest is not None
        overlay_found, ovl_digest, ovl_base_digest, ovl_conflict = _lookup_overlay(
            overlays, target, pub, desc
        )
        if not available:
            ovl_digest = None
            ovl_base_digest = None

        raw_facts = desc.get("facts") if isinstance(desc, dict) and isinstance(desc.get("facts"), dict) else (desc or {})
        facts_digest = raw_facts.get("digest")
        facts_bound = available and (facts_digest in (None, "", pm_digest))
        desktop_val = str(raw_facts.get("desktop") if facts_bound and raw_facts.get("desktop") is not None else _default_desktop(target["flavor"]))
        kernel_val = str(raw_facts.get("kernelVer") or "") if facts_bound else ""
        sd_boot_val = bool(raw_facts.get("hasSdBoot", False)) if facts_bound else False
        pkg_mgr_val = str(raw_facts.get("pkgManager") or "") if facts_bound else ""
        repo_fam_val = str(raw_facts.get("repoFamily") or "") if facts_bound else ""
        layer_count_val = int(raw_facts.get("layerCount", 0) or 0) if facts_bound else 0
        comp_size_val = int(raw_facts.get("compressedSize", 0) or 0) if facts_bound else 0
        bootc_val = bool(raw_facts.get("bootc", True)) if facts_bound else False

        facts = {
            "digest": pm_digest if available else None,
            "desktop": desktop_val,
            "kernelVer": kernel_val,
            "hasSdBoot": sd_boot_val,
            "pkgManager": pkg_mgr_val,
            "repoFamily": repo_fam_val,
            "layerCount": layer_count_val,
            "compressedSize": comp_size_val,
            "bootc": bootc_val,
        }

        inst_rev = str(
            (desc.get("installerRevision") if isinstance(desc, dict) and desc.get("installerRevision") is not None else installer_revision) or ""
        )
        eng_rev = str(
            (desc.get("engineRevision") if isinstance(desc, dict) and desc.get("engineRevision") is not None else engine_revision) or ""
        )
        resolved_inputs = {
            "platformManifestDigest": pm_digest,
            "indexDigest": idx_digest,
            "configDigest": cfg_digest,
            "liveOverlayDigest": ovl_digest,
            "liveOverlayBaseDigest": ovl_base_digest,
            "installerRevision": inst_rev,
            "engineRevision": eng_rev,
        }

        qual_status = "unqualified"
        qual_reason: str | None = "untested-snapshot"
        qualified_at: str | None = None
        receipt_digest: str | None = None
        browser_info: Any = None
        resources_info: Any = None

        if _is_unsupported_target(target):
            qual_status = "unsupported"
            qual_reason = "hardware-scope-unsupported"
        elif not available:
            qual_status = "unqualified"
            qual_reason = "missing-platform-descriptor"
        elif ovl_conflict or (
            overlay_found and (ovl_base_digest is None or ovl_base_digest != pm_digest)
        ):
            qual_status = "unqualified"
            qual_reason = "overlay-base-digest-mismatch"
        elif overlays is not None and not overlay_found:
            qual_status = "unqualified"
            qual_reason = "missing-live-overlay"
        else:
            matched_receipt, saw_stale = _match_receipt(receipts, target, pub, pm_digest, ovl_digest)
            if matched_receipt is not None:
                rec_status = matched_receipt.get("status")
                checks = matched_receipt.get("checks")
                checks_failed = isinstance(checks, list) and any(
                    isinstance(c, dict) and c.get("status") not in (None, "pass", "passed", "success")
                    for c in checks
                )
                if rec_status in {"fail", "failed", "unqualified", "blocked"} or checks_failed:
                    qual_status = "unqualified"
                    qual_reason = str(matched_receipt.get("reason") or "qualification-failed")
                elif rec_status == "local-only" or matched_receipt.get("localOnly") is True:
                    qual_status = "local-only"
                    qual_reason = str(matched_receipt.get("reason") or "local-only-target")
                    qualified_at = str(
                        matched_receipt.get("qualifiedAt")
                        or matched_receipt.get("measuredAt")
                        or matched_receipt.get("generatedAt")
                        or ""
                    ) or None
                    raw_rd = matched_receipt.get("receiptDigest") or matched_receipt.get("contractDigest")
                    receipt_digest = (
                        _optional_digest(raw_rd, "receiptDigest")
                        if raw_rd
                        else "sha256:" + hashlib.sha256(_canonical_json(matched_receipt)).hexdigest()
                    )
                    browser_info = matched_receipt.get("browser")
                    resources_info = matched_receipt.get("resources")
                else:
                    qual_status = "qualified"
                    qual_reason = None
                    qualified_at = str(
                        matched_receipt.get("qualifiedAt")
                        or matched_receipt.get("measuredAt")
                        or matched_receipt.get("generatedAt")
                        or ""
                    ) or None
                    raw_rd = matched_receipt.get("receiptDigest") or matched_receipt.get("contractDigest")
                    receipt_digest = (
                        _optional_digest(raw_rd, "receiptDigest")
                        if raw_rd
                        else "sha256:" + hashlib.sha256(_canonical_json(matched_receipt)).hexdigest()
                    )
                    browser_info = matched_receipt.get("browser")
                    resources_info = matched_receipt.get("resources")
            else:
                qual_status = "unqualified"
                qual_reason = "stale-qualification-receipt" if saw_stale else "untested-snapshot"

        entry = {
            "target": target,
            "targetKey": tkey,
            "required": bool(record["required"]),
            "scheduled": bool(record["scheduled"]),
            "publication": {
                "repository": repo,
                "tag": tag,
                "ref": ref,
            },
            "availability": {
                "available": available,
                "ociPlatform": _oci_platform(target["platform"]),
            },
            "resolvedInputs": resolved_inputs,
            "facts": facts,
            "qualification": {
                "status": qual_status,
                "reason": qual_reason,
                "qualifiedAt": qualified_at,
                "receiptDigest": receipt_digest,
                "browser": browser_info,
                "resources": resources_info,
            },
        }
        validate_catalog_entry(entry)
        entries.append(entry)

    snapshot = {
        "schemaVersion": 1,
        "kind": "catalog-snapshot",
        "producerRevision": str(producer_revision or ""),
        "generatedAt": str(generated_at or ""),
        "coverageDigest": coverage["coverageDigest"],
        "snapshotDigest": "sha256:" + hashlib.sha256(_canonical_json(entries)).hexdigest(),
        "targets": entries,
    }
    validate_catalog_snapshot(snapshot)
    return snapshot


def downgrade_stale_targets(
    snapshot: dict[str, Any],
    current_descriptors: Any = None,
    current_overlays: Any = None,
    current_pins: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rewrite qualified/local-only entries whose inputs moved since their receipt matched.

    A qualified entry is digest-bound to its receipt at build time, so the
    entry's recorded platform digest, overlay digest and installer/engine
    revisions stand in for the receipt's. Any current input that differs from
    the recorded one rewrites the entry to unqualified/stale-qualification-receipt
    while keeping its qualifiedAt, receiptDigest, browser and resources as dated
    provenance. Inputs left as None are not evaluated and cannot stale an entry.
    """
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("targets"), list):
        raise ValueError("downgrade requires a catalog snapshot mapping")
    if current_pins is not None and not isinstance(current_pins, dict):
        raise ValueError("current_pins must be a mapping")
    pins = current_pins or {}
    pin_installer = pins.get("installerRevision", pins.get("installer_revision", ""))
    pin_engine = pins.get("engineRevision", pins.get("engine_revision", ""))

    entries = copy.deepcopy(snapshot["targets"])
    current_by_key: dict[str, dict[str, Any]] = {}
    if current_descriptors is not None:
        required_by_key = {target_key(entry["target"]): {"target": entry["target"]} for entry in entries}
        current_by_key, _ = _index_descriptors(current_descriptors, {"variants": []}, required_by_key)

    for entry in entries:
        qual = entry["qualification"]
        if qual["status"] not in {"qualified", "local-only"}:
            continue
        stale = False
        current_desc = current_by_key.get(entry["targetKey"]) if current_descriptors is not None else None
        if current_descriptors is not None:
            _, current_pm, _ = _resolve_descriptor_digests(current_desc)
            if current_pm != entry["facts"]["digest"]:
                stale = True
        if not stale and current_overlays is not None:
            _, current_ovl, _, _ = _lookup_overlay(
                current_overlays, entry["target"], entry["publication"], current_desc
            )
            if current_ovl != entry["resolvedInputs"].get("liveOverlayDigest"):
                stale = True
        if not stale and pins:
            for field, current_pin in (
                ("installerRevision", pin_installer),
                ("engineRevision", pin_engine),
            ):
                recorded = entry["resolvedInputs"].get(field)
                if current_pin not in (None, "") and recorded not in (None, "") and current_pin != recorded:
                    stale = True
                    break
        if stale:
            entry["qualification"] = {
                "status": "unqualified",
                "reason": "stale-qualification-receipt",
                "qualifiedAt": qual.get("qualifiedAt"),
                "receiptDigest": qual.get("receiptDigest"),
                "browser": qual.get("browser"),
                "resources": qual.get("resources"),
            }
            validate_catalog_entry(entry)

    downgraded = dict(snapshot)
    downgraded["targets"] = entries
    downgraded["snapshotDigest"] = "sha256:" + hashlib.sha256(_canonical_json(entries)).hexdigest()
    validate_catalog_snapshot(downgraded)
    return downgraded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(".github/build-config.yml"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    import yaml
    document = coverage_document(yaml.safe_load(args.config.read_text()))
    body = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(body)
    else:
        print(body, end="")


if __name__ == "__main__":
    main()
