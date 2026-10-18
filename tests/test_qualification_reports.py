"""Dated qualification status and performance reports (Task 13).

Falsification: a moved tag, a changed overlay/engine input without a matching
receipt, a failing/skipped check, or a malformed digest must never read as
qualified. Every catalog candidate carries dated evidence or an explicit
blocker, and the ISO gate stays wired so skipped/unexercised assertions
cannot pass.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from contracts import targets

_spec = importlib.util.spec_from_file_location(
    "build_health_collector", ROOT / "scripts" / "gen-build-health.py"
)
collector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collector)

_cspec = importlib.util.spec_from_file_location(
    "check_ci_contract", ROOT / "scripts" / "check-ci-contract.py"
)
contract = importlib.util.module_from_spec(_cspec)
_cspec.loader.exec_module(contract)

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
SOURCE = "c" * 40

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
DIGEST_E = "sha256:" + "e" * 64
DIGEST_F = "sha256:" + "f" * 64
DIGEST_1 = "sha256:" + "1" * 64
DIGEST_2 = "sha256:" + "2" * 64
def config():
    return {"config": {"required_platforms": ["linux/amd64", "linux/arm64"]},
            "variants": [{"id": "albacore", "platforms": ["linux/amd64"],
                          "flavors": [{"id": "cosmic", "build_image": True}]},
                         {"id": "skipjack", "experimental": True,
                          "platforms": ["linux/amd64", "linux/arm64"],
                          "flavors": [{"id": "cosmic-hwe", "build_image": True},
                                      {"id": "gnome-asahi", "build_image": True,
                                       "platforms": ["linux/arm64"]},
                                      {"id": "gnome-t2", "build_image": True,
                                       "platforms": ["linux/amd64"]},
                                      {"id": "xfce", "build_image": False}]}]}


def v1_receipt(**over):
    receipt = {
        "variant": "albacore",
        "flavor": "cosmic",
        "platform": "linux/amd64/v2",
        "source_image_digest": DIGEST_B,
        "overlay": DIGEST_1,
        "measured_at": "2026-10-17T01:02:03Z",
        "receipt_digest": DIGEST_C,
        "browser": {"name": "Chromium", "version": "140.0"},
        "resources": {"cpu": "4"},
        "measurements": {"cold": {"duration_s": 61.5}, "warm": {"duration_s": 12.0}},
        "evidence": [{"url": "https://example.invalid/run/1"}],
    }
    receipt.update(over)
    return receipt


def qualified_snapshot():
    data = config()
    descriptors = {
        "albacore:cosmic:linux/amd64/v2": {
            "indexDigest": DIGEST_A,
            "platformManifestDigest": DIGEST_B,
            "configDigest": DIGEST_C,
            "ociPlatform": {"os": "linux", "architecture": "amd64", "variant": "v2"},
        },
        "skipjack:cosmic-hwe:linux/amd64": {
            "platformManifestDigest": DIGEST_D,
            "ociPlatform": {"os": "linux", "architecture": "amd64", "variant": None},
        },
    }
    overlays = {
        "albacore:cosmic:linux/amd64/v2": {
            "liveOverlayDigest": DIGEST_1,
            "liveOverlayBaseDigest": DIGEST_B,
        },
        "skipjack:cosmic-hwe:linux/amd64": {
            "liveOverlayDigest": DIGEST_2,
            "liveOverlayBaseDigest": DIGEST_D,
        },
    }
    receipts = [
        {
            "variant": "albacore",
            "flavor": "cosmic",
            "platform": "linux/amd64/v2",
            "platformManifestDigest": DIGEST_B,
            "liveOverlayDigest": DIGEST_1,
            "qualifiedAt": "2026-10-17T01:02:03Z",
            "receiptDigest": DIGEST_C,
            "browser": {"name": "Chromium", "version": "140.0"},
            "resources": {"cpu": "4"},
        },
        {
            "variant": "skipjack",
            "flavor": "cosmic-hwe",
            "platform": "linux/amd64",
            "platformManifestDigest": DIGEST_D,
            "liveOverlayDigest": DIGEST_2,
            "localOnly": True,
            "reason": "qemu-only-verification",
            "qualifiedAt": "2026-10-17T02:00:00Z",
        },
    ]
    snapshot = targets.catalog_snapshot(
        data, descriptors=descriptors, overlays=overlays, receipts=receipts,
        producer_revision="rev-1", generated_at="2026-10-17T03:00:00Z",
        installer_revision="inst-1", engine_revision="eng-1",
    )
    return snapshot, descriptors, overlays


# ── 1. receipt_to_catalog_projection ──────────────────────────────────────────

def test_v1_receipt_projects_to_qualified_with_date_digest_browser_passthrough():
    projected = targets.receipt_to_catalog_projection(v1_receipt())
    assert projected["platformManifestDigest"] == DIGEST_B
    assert projected["liveOverlayDigest"] == DIGEST_1
    assert projected["qualifiedAt"] == "2026-10-17T01:02:03Z"
    assert projected["receiptDigest"] == DIGEST_C
    assert projected["browser"] == {"name": "Chromium", "version": "140.0"}
    assert projected["resources"] == {"cpu": "4"}
    assert projected["resolvedInputs"]["platformManifestDigest"] == DIGEST_B
    snapshot = targets.catalog_snapshot(
        config(),
        descriptors={"albacore:cosmic:linux/amd64/v2": {
            "platformManifestDigest": DIGEST_B,
            "ociPlatform": {"os": "linux", "architecture": "amd64", "variant": "v2"}}},
        overlays={"albacore:cosmic:linux/amd64/v2": {
            "liveOverlayDigest": DIGEST_1, "liveOverlayBaseDigest": DIGEST_B}},
        receipts=[targets.receipt_to_catalog_projection(v1_receipt())],
    )
    entry = next(e for e in snapshot["targets"]
                 if e["targetKey"] == "albacore:cosmic:linux/amd64/v2")
    assert entry["qualification"]["status"] == "qualified"
    assert entry["qualification"]["qualifiedAt"] == "2026-10-17T01:02:03Z"
    assert entry["qualification"]["receiptDigest"] == DIGEST_C


@pytest.mark.parametrize("receipt", [
    v1_receipt(status="fail"),
    v1_receipt(status="failed"),
    v1_receipt(checks=[{"name": "install", "status": "pass"},
                       {"name": "boot", "status": "skipped"}]),
    v1_receipt(checks=[{"name": "install", "status": "fail"}]),
])
def test_failing_or_skipped_checks_never_project_to_qualified(receipt):
    snapshot = targets.catalog_snapshot(
        config(),
        descriptors={"albacore:cosmic:linux/amd64/v2": {
            "platformManifestDigest": DIGEST_B,
            "ociPlatform": {"os": "linux", "architecture": "amd64", "variant": "v2"}}},
        overlays={"albacore:cosmic:linux/amd64/v2": {
            "liveOverlayDigest": DIGEST_1, "liveOverlayBaseDigest": DIGEST_B}},
        receipts=[targets.receipt_to_catalog_projection(receipt)],
    )
    entry = next(e for e in snapshot["targets"]
                 if e["targetKey"] == "albacore:cosmic:linux/amd64/v2")
    assert entry["qualification"]["status"] == "unqualified"
    assert entry["qualification"]["reason"]
    assert entry["qualification"]["qualifiedAt"] is None


@pytest.mark.parametrize("field,value", [
    ("source_image_digest", "sha256:zzzz"),
    ("source_image_digest", "not-a-digest"),
    ("receipt_digest", "sha256:short"),
])
def test_malformed_digests_fail_closed(field, value):
    with pytest.raises(ValueError):
        targets.receipt_to_catalog_projection(v1_receipt(**{field: value}))


def test_non_mapping_receipt_fails_closed():
    with pytest.raises(ValueError):
        targets.receipt_to_catalog_projection(["not", "a", "mapping"])


# ── 2. downgrade_stale_targets ────────────────────────────────────────────────

def test_overlay_move_downgrades_with_provenance_intact():
    snapshot, _, overlays = qualified_snapshot()
    moved = copy.deepcopy(overlays)
    moved["albacore:cosmic:linux/amd64/v2"] = {
        "liveOverlayDigest": DIGEST_2, "liveOverlayBaseDigest": DIGEST_B}
    downgraded = targets.downgrade_stale_targets(snapshot, current_overlays=moved)
    entry = next(e for e in downgraded["targets"]
                 if e["targetKey"] == "albacore:cosmic:linux/amd64/v2")
    assert entry["qualification"]["status"] == "unqualified"
    assert entry["qualification"]["reason"] == "stale-qualification-receipt"
    assert entry["qualification"]["qualifiedAt"] == "2026-10-17T01:02:03Z"
    assert entry["qualification"]["receiptDigest"] == DIGEST_C
    assert entry["qualification"]["browser"] == {"name": "Chromium", "version": "140.0"}
    assert entry["qualification"]["resources"] == {"cpu": "4"}


def test_moved_tag_without_matching_receipt_downgrades():
    snapshot, descriptors, _ = qualified_snapshot()
    moved = copy.deepcopy(descriptors)
    moved["albacore:cosmic:linux/amd64/v2"]["platformManifestDigest"] = DIGEST_E
    downgraded = targets.downgrade_stale_targets(
        snapshot, current_descriptors=moved)
    entry = next(e for e in downgraded["targets"]
                 if e["targetKey"] == "albacore:cosmic:linux/amd64/v2")
    assert entry["qualification"]["status"] == "unqualified"
    assert entry["qualification"]["reason"] == "stale-qualification-receipt"


@pytest.mark.parametrize("pins", [
    {"installerRevision": "inst-2"},
    {"engineRevision": "eng-2"},
])
def test_engine_or_installer_pin_change_downgrades(pins):
    snapshot, _, _ = qualified_snapshot()
    downgraded = targets.downgrade_stale_targets(snapshot, current_pins=pins)
    for key in ("albacore:cosmic:linux/amd64/v2",
                "skipjack:cosmic-hwe:linux/amd64"):
        entry = next(e for e in downgraded["targets"] if e["targetKey"] == key)
        assert entry["qualification"]["status"] == "unqualified"
        assert entry["qualification"]["reason"] == "stale-qualification-receipt"


def test_unchanged_inputs_keep_entries_identical_and_digest_stable():
    snapshot, descriptors, overlays = qualified_snapshot()
    downgraded = targets.downgrade_stale_targets(
        snapshot, current_descriptors=descriptors, current_overlays=overlays,
        current_pins={"installerRevision": "inst-1", "engineRevision": "eng-1"})
    assert downgraded["targets"] == snapshot["targets"]
    assert downgraded["snapshotDigest"] == snapshot["snapshotDigest"]


def test_none_inputs_skip_downgrade():
    snapshot, _, _ = qualified_snapshot()
    downgraded = targets.downgrade_stale_targets(snapshot)
    assert downgraded["targets"] == snapshot["targets"]
    assert downgraded["snapshotDigest"] == snapshot["snapshotDigest"]


# ── 3. catalog_snapshot end-to-end with projected receipts ────────────────────

def test_projected_receipts_cover_every_candidate_with_four_distinct_states():
    data = config()
    descriptors = {
        "albacore:cosmic:linux/amd64/v2": {
            "platformManifestDigest": DIGEST_B,
            "ociPlatform": {"os": "linux", "architecture": "amd64", "variant": "v2"},
        },
        "skipjack:cosmic-hwe:linux/amd64": {
            "platformManifestDigest": DIGEST_D,
            "ociPlatform": {"os": "linux", "architecture": "amd64", "variant": None},
        },
        "skipjack:cosmic-hwe:linux/arm64": {
            "platformManifestDigest": DIGEST_E,
            "ociPlatform": {"os": "linux", "architecture": "arm64", "variant": None},
        },
    }
    overlays = {
        "albacore:cosmic:linux/amd64/v2": {
            "liveOverlayDigest": DIGEST_1, "liveOverlayBaseDigest": DIGEST_B},
        "skipjack:cosmic-hwe:linux/amd64": {
            "liveOverlayDigest": DIGEST_2, "liveOverlayBaseDigest": DIGEST_D},
        "skipjack:cosmic-hwe:linux/arm64": {
            "liveOverlayDigest": DIGEST_2, "liveOverlayBaseDigest": DIGEST_E},
    }
    raw_receipts = [
        v1_receipt(),
        {"variant": "skipjack", "flavor": "cosmic-hwe", "platform": "linux/amd64",
         "source_image_digest": DIGEST_D, "overlay": DIGEST_2,
         "local_only": True, "reason": "qemu-only-verification",
         "qualified_at": "2026-10-17T02:00:00Z"},
    ]
    receipts = [targets.receipt_to_catalog_projection(r) for r in raw_receipts]
    snapshot = targets.catalog_snapshot(
        data, descriptors=descriptors, overlays=overlays, receipts=receipts,
        generated_at="2026-10-17T03:00:00Z")
    targets.validate_catalog_snapshot(snapshot)

    required_keys = {targets.target_key(r["target"])
                     for r in targets.coverage_document(data)["targets"]}
    assert required_keys <= {e["targetKey"] for e in snapshot["targets"]}
    states = {e["qualification"]["status"] for e in snapshot["targets"]}
    assert {"qualified", "local-only", "unqualified", "unsupported"} <= states
    for entry in snapshot["targets"]:
        qual = entry["qualification"]
        if qual["status"] == "qualified":
            assert qual["qualifiedAt"], entry["targetKey"]
            assert qual["receiptDigest"], entry["targetKey"]
        else:
            assert isinstance(qual["reason"], str) and qual["reason"], entry["targetKey"]


# ── 4. iso gate wiring ────────────────────────────────────────────────────────

def test_iso_gate_is_wired_reachable_and_sla_consistent():
    criteria = contract.load_criteria(ROOT / ".github" / "green-criteria.yml")
    workflows = contract.load_workflows()
    iso = next(c for c in criteria if c["id"] == "iso")
    assert iso["enforcement"] == "advisory"
    assert iso["graduation"]["required_consecutive_passes"] == 2
    assert contract.violations_for(iso, workflows) == []


def test_stale_or_partial_receipts_cannot_score_qualified():
    data = config()
    descriptors = {"albacore:cosmic:linux/amd64/v2": {
        "platformManifestDigest": DIGEST_B,
        "ociPlatform": {"os": "linux", "architecture": "amd64", "variant": "v2"}}}
    stale = {"variant": "albacore", "flavor": "cosmic",
             "platform": "linux/amd64/v2",
             "platformManifestDigest": DIGEST_A,
             "qualifiedAt": "2026-10-16T00:00:00Z", "receiptDigest": DIGEST_C}
    snapshot = targets.catalog_snapshot(
        data, descriptors=descriptors, receipts={"albacore:cosmic:linux/amd64/v2": stale})
    entry = next(e for e in snapshot["targets"]
                 if e["targetKey"] == "albacore:cosmic:linux/amd64/v2")
    assert entry["qualification"]["status"] == "unqualified"
    assert entry["qualification"]["reason"] == "stale-qualification-receipt"

    bad = copy.deepcopy(entry)
    bad["qualification"] = {"status": "qualified", "reason": None,
                            "qualifiedAt": "2026-10-17T00:00:00Z",
                            "receiptDigest": None, "browser": None, "resources": None}
    with pytest.raises(ValueError, match="receiptDigest"):
        targets.validate_catalog_entry(bad)


# ── 5. gen-build-health collect with receipts ─────────────────────────────────

def single_variant_config():
    return {"variants": [{"id": "albacore", "flavors": [
        {"id": "cosmic", "build_image": True,
         "platforms": ["linux/amd64/v2", "linux/arm64"]}]}]}


def test_collect_with_receipts_reports_qualification_and_validates():
    receipts = {"albacore:cosmic:linux/amd64/v2": dict(
        v1_receipt(), platform="linux/amd64/v2")}
    document = collector.collect(
        single_variant_config(), SOURCE, lambda _: {"workflow_runs": []},
        now=NOW, receipts=receipts)
    collector.validate(document, expected_kind="build-health", now=NOW)
    intel = next(r for r in document["targets"]
                 if r["target"]["platform"] == "linux/amd64/v2")
    qual = intel["qualification"]
    assert qual["status"] == "qualified"
    assert qual["qualifiedAt"] == "2026-10-17T01:02:03Z"
    assert qual["receiptDigest"] == DIGEST_C
    assert qual["browser"] == "Chromium 140.0"
    assert qual["coldSeconds"] == 61.5
    assert qual["warmSeconds"] == 12.0
    assert qual["evidence"] == [{"url": "https://example.invalid/run/1"}]


def test_collect_default_path_shape_unchanged_without_receipts():
    document = collector.collect(
        single_variant_config(), SOURCE, lambda _: {"workflow_runs": []}, now=NOW)
    collector.validate(document, expected_kind="build-health", now=NOW)
    assert all("qualification" not in row for row in document["targets"])
