"""One ISO per base+desktop, each embedding its own NVIDIA and HWE flavors.

`iso_groups` already built deduplicated multi-image ISOs — the GNOME group
ships `<variant>.iso` carrying gnome, gnome-hwe, gnome-nvidia and
gnome-nvidia-hwe in one offline store, so a user downloads one ISO and the
installer picks the right image. That is the shape wanted everywhere.

The other four desktops did not have it. They shared a single `community`
group that packed KDE, COSMIC, Niri and XFCE into ONE ISO and carried
`publish: false`, on the reasoning that the browser ISO Builder covers the
long tail on demand so a five-flavor offline store was not worth the storage.

The cost argument was sound; the conclusion was not. Someone who wants KDE
should get a KDE ISO, not a four-desktop ISO and not a browser build step.
And these are deduplicated groups over a shared squashfs, so per-desktop ISOs
do not multiply storage the way per-flavor ISOs did — that was the thing
grouping was introduced to stop.

Guarded by tests because the config is what the whole publish pipeline reads,
and a typo here is a silently missing ISO rather than an error.
"""
from __future__ import annotations

from pathlib import Path

import importlib.util

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
DESKTOPS = ["gnome", "kde", "cosmic", "niri", "xfce"]


def _delivery_cutover():
    spec = importlib.util.spec_from_file_location(
        "delivery_cutover", ROOT / "scripts" / "delivery-cutover.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DC = _delivery_cutover()

DIGEST = "sha256:" + "ab" * 32

def config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def groups() -> list[dict]:
    g = config()["iso_groups"]
    assert g, "iso_groups is empty; every assertion below would be vacuous"
    return g


def test_there_is_one_group_per_desktop():
    by_desktop = {}
    for g in groups():
        # The flagship group's suffix is "" and it is the gnome one.
        desktop = g.get("suffix") or "gnome"
        assert desktop not in by_desktop, f"two groups claim {desktop}"
        by_desktop[desktop] = g
    assert sorted(by_desktop) == sorted(DESKTOPS), sorted(by_desktop)


def test_no_group_packs_more_than_one_desktop():
    """The `community` group put four desktops in one ISO.

    A group is single-desktop when every flavor it names, live and offline,
    starts with that desktop's id.
    """
    for g in groups():
        desktop = g.get("suffix") or "gnome"
        named = list(g["flavors"]) + list(g["offline_flavors"])
        for f in named:
            assert f.split("-")[0] == desktop, (
                f"group {desktop!r} names {f!r} from another desktop"
            )


def test_every_group_embeds_its_own_nvidia_and_hwe():
    """The point of grouping: one download, the installer picks the image."""
    for g in groups():
        desktop = g.get("suffix") or "gnome"
        offline = set(g["offline_flavors"])
        assert desktop in offline, (desktop, offline)
        assert any("nvidia" in f for f in offline), (desktop, offline)
        assert any("hwe" in f for f in offline), (desktop, offline)


def test_every_group_is_published():
    """`publish: false` is what kept four desktops off the download page."""
    for g in groups():
        assert g.get("publish", True) is not False, g


def test_the_live_flavor_is_the_nvidia_one():
    """The ISO boots the NVIDIA image so a machine with the card works on
    first boot; the non-NVIDIA images ride along in the offline store."""
    for g in groups():
        assert g["flavors"], g
        for f in g["flavors"]:
            assert "nvidia" in f, (g.get("suffix"), f)


def test_no_group_names_a_flavor_no_variant_has():
    """A typo here is a silently missing ISO, not an error.

    Both the matrix generator and build-iso-group.sh intersect group flavors
    against each variant's real ones, so a flavor that no variant defines is
    dropped everywhere and the group quietly shrinks or vanishes.
    """
    cfg = config()
    defined = {f["id"] for v in cfg["variants"] for f in v.get("flavors", [])}
    for g in groups():
        for f in list(g["flavors"]) + list(g["offline_flavors"]):
            assert f in defined, f"{f!r} is not a flavor of any variant"


def test_the_intersection_that_makes_partial_variants_safe_still_exists():
    """skipjack has no xfce-nvidia; bonito has no kde-hwe.

    Those groups must shrink or be skipped rather than fail the build. Both
    halves of that are asserted here because a group referencing a flavor a
    variant lacks is now the normal case, not an edge one.
    """
    builder = (ROOT / "scripts" / "build-iso-group.sh").read_text(encoding="utf-8")
    assert "Intersect, preserving group/offline order." in builder
    assert "SELECTED_OFFLINE=()" in builder

    wf = (ROOT / ".github" / "workflows" / "publish-iso-groups.yml").read_text(
        encoding="utf-8")
    assert "iso_groups ∩ variant flavors" in wf
    assert "select(($sel | length) > 0)" in wf

def _full_group_entries(cfg: dict, variant: str, suffix: str) -> list[dict]:
    """A cutover entry for every member x platform target of a group."""
    live, offline = DC.group_members(cfg, variant, suffix)
    entries = []
    for flavor in dict.fromkeys(live + offline):
        for platform in DC.required_platforms_for(cfg, variant, flavor):
            entries.append({
                "target": {"variant": variant, "flavor": flavor, "platform": platform},
                "evidence": {"receiptDigest": DIGEST, "qualifiedAt": "2026-10-01T00:00:00Z"},
                "preset": "test-preset",
            })
    return entries


def test_empty_policy_covers_no_group_so_every_group_still_publishes():
    """The default path: with the empty initial policy no group's upload is
    suppressed, so the universal-publication shape above is what ships."""
    cfg = config()
    policy = {"cutover": [], "retained": []}
    probed = 0
    for group in groups():
        suffix = group.get("suffix") or ""
        for variant in cfg["variants"]:
            live, offline = DC.group_members(cfg, variant["id"], suffix)
            if not live and not offline:
                continue
            probed += 1
            assert DC.group_covered(
                policy, variant["id"], suffix, live, offline, config=cfg
            ) is False, (variant["id"], suffix)
    assert probed > 0, "no variant x group probed; the loop above is vacuous"


def test_cut_over_group_suppresses_only_that_group():
    """Per-target cutover: a fully qualified group stops publishing while
    every other group and variant keeps publishing as today."""
    cfg = config()
    live, offline = DC.group_members(cfg, "yellowfin", "kde")
    assert live and offline
    entries = _full_group_entries(cfg, "yellowfin", "kde")
    policy = {"cutover": entries, "retained": []}
    from contracts.targets import _oci_platform, catalog_snapshot, cpu_baseline

    descriptors = {}
    receipts = {}
    overlays = {}
    for entry in entries:
        target = entry["target"]
        key = f"{target['variant']}:{target['flavor']}:{target['platform']}"
        platform_digest = "sha256:" + "01" * 32
        descriptors[key] = {
            "platformManifestDigest": platform_digest,
            "ociPlatform": _oci_platform(target["platform"]),
        }
        overlays[key] = {"liveOverlayDigest": DIGEST,
                         "liveOverlayBaseDigest": platform_digest}
        receipts[key] = strict_receipt(
            target, source=platform_digest, overlay=DIGEST,
            installer=DIGEST, engine=DIGEST,
            cpu_baseline=cpu_baseline(target["variant"], target["platform"]))
        entry["evidence"]["receiptDigest"] = receipts[key]["receiptDigest"]
    snapshot = catalog_snapshot(
        cfg, descriptors=descriptors, overlays=overlays, receipts=receipts,
        installer_revision=DIGEST, engine_revision=DIGEST)
    assert DC.group_covered(
        policy, "yellowfin", "kde", live, offline,
        config=cfg, snapshot=snapshot,
        current_descriptors=descriptors,
        current_overlays=overlays,
        current_pins={"installerRevision": DIGEST, "engineRevision": DIGEST},
    ) is True
    for suffix in ("", "cosmic", "niri", "xfce"):
        other_live, other_offline = DC.group_members(cfg, "yellowfin", suffix)
        if not other_live and not other_offline:
            continue
        assert DC.group_covered(
            policy, "yellowfin", suffix, other_live, other_offline, config=cfg
        ) is False, suffix
    bonito_live, bonito_offline = DC.group_members(cfg, "bonito", "kde")
    assert DC.group_covered(
        policy, "bonito", "kde", bonito_live, bonito_offline, config=cfg
    ) is False


import hashlib
import json


def strict_receipt(target, *, source, overlay, installer, engine, cpu_baseline):
    observed = {
        "installed_boot": True, "desktop_contract": True,
        "source_digest": source, "booted_digest": source,
        "target_imgref": "ghcr.io/tuna-os/test@" + source, "duration_s": 1,
    }
    receipt = {
        "schema": "QualificationEvidence/v1", **target,
        "cpu_baseline": cpu_baseline, "hardware_scope": "qemu",
        "resolved_inputs": {"source": source, "overlay": overlay,
                            "installer": installer, "engine": engine},
        "browser": {"name": "chromium", "version": "test-only",
                    "memory_gib": 8, "free_disk_gib": 20},
        "offline_network_disabled": True,
        "observed": {"plain": dict(observed), "encrypted": dict(observed)},
        "measurements": {"cold": {"duration_s": 1}, "warm": {"duration_s": 1}},
        "qualifiedAt": "2026-10-01T00:00:00Z",
    }
    receipt["receiptDigest"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return receipt
