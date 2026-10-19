"""Dated qualification status and performance reports (Task 13).

Falsification: a moved tag, a changed overlay/engine input without a matching
receipt, a failing/skipped check, or a malformed digest must never read as
qualified. Every catalog candidate carries dated evidence or an explicit
blocker, and the ISO gate stays wired so skipped/unexercised assertions
cannot pass.
"""

from __future__ import annotations

import copy
import hashlib
import json
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


def catalog_receipt():
    """Synthetic strict evidence for unit tests; never distributed as proof."""
    receipt = _strict_v1_receipt()
    receipt["resolved_inputs"].update(source=DIGEST_B, overlay=DIGEST_1)
    for record in receipt["observed"].values():
        record.update(source_digest=DIGEST_B, booted_digest=DIGEST_B)
    receipt["resources"] = {"cpu": "4"}
    receipt["build_provenance"] = {"origin": "browser", "receipt_digest": DIGEST_E,
                                   "iso_digest": DIGEST_F, "browser": dict(receipt["browser"])}
    receipt.pop("receiptDigest")
    receipt["receiptDigest"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
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
        catalog_receipt(),
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
        installer_revision=DIGEST_C, engine_revision=DIGEST_D,
        browser_builds={"albacore:cosmic:linux/amd64/v2": catalog_receipt()["build_provenance"]},
    )
    return snapshot, descriptors, overlays


# ── 1. receipt_to_catalog_projection ──────────────────────────────────────────

def test_legacy_projection_preserves_metadata_but_cannot_qualify():
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
    assert entry["qualification"]["status"] == "unqualified"
    assert entry["qualification"]["reason"] == "invalid-qualification-evidence"



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
    assert entry["qualification"]["receiptDigest"] == catalog_receipt()["receiptDigest"]
    assert entry["qualification"]["browser"] == catalog_receipt()["browser"]
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
        current_pins={"installerRevision": DIGEST_C, "engineRevision": DIGEST_D})
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
        catalog_receipt(),
        {"variant": "skipjack", "flavor": "cosmic-hwe", "platform": "linux/amd64",
         "source_image_digest": DIGEST_D, "overlay": DIGEST_2,
         "local_only": True, "reason": "qemu-only-verification",
         "qualified_at": "2026-10-17T02:00:00Z"},
    ]
    receipts = [targets.receipt_to_catalog_projection(r) for r in raw_receipts]
    snapshot = targets.catalog_snapshot(
        data, descriptors=descriptors, overlays=overlays, receipts=receipts,
        generated_at="2026-10-17T03:00:00Z",
        installer_revision=DIGEST_C, engine_revision=DIGEST_D,
        browser_builds={"albacore:cosmic:linux/amd64/v2": catalog_receipt()["build_provenance"]})
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


def test_collect_with_receipts_preserves_diagnostics_without_qualification():
    receipts = {"albacore:cosmic:linux/amd64/v2": dict(
        _strict_v1_receipt(), evidence=[{"url": "https://example.invalid/run/1"}])}
    document = collector.collect(
        single_variant_config(), SOURCE, lambda _: {"workflow_runs": []},
        now=NOW, receipts=receipts)
    collector.validate(document, expected_kind="build-health", now=NOW)
    intel = next(r for r in document["targets"]
                 if r["target"]["platform"] == "linux/amd64/v2")
    qual = intel["qualification"]
    assert qual["status"] == "unqualified"
    assert qual["qualifiedAt"] == "2026-10-17T01:02:03Z"
    assert qual["receiptDigest"] == DIGEST_C
    assert qual["browser"] == "chromium 140.0"
    assert qual["coldSeconds"] == 60.0
    assert qual["warmSeconds"] == 12.0
    assert qual["evidence"] == [{"url": "https://example.invalid/run/1"}]


def test_collect_incomplete_receipt_cannot_score_qualified():
    receipt = v1_receipt()
    receipt.pop("source_image_digest")
    receipts = {"albacore:cosmic:linux/amd64/v2": receipt}
    document = collector.collect(
        single_variant_config(), SOURCE, lambda _: {"workflow_runs": []},
        now=NOW, receipts=receipts,
    )
    intel = next(
        row for row in document["targets"]
        if row["target"]["platform"] == "linux/amd64/v2"
    )
    assert intel["qualification"]["status"] == "unqualified"


def _strict_v1_receipt(*, installed_boot=True):
    digest = "sha256:" + "a" * 64
    record = {
        "installed_boot": installed_boot,
        "desktop_contract": True,
        "source_digest": digest,
        "booted_digest": digest,
        "target_imgref": "ghcr.io/tuna-os/albacore:cosmic",
        "duration_s": 123.0,
    }
    return {
        "schema": "QualificationEvidence/v1",
        "variant": "albacore",
        "flavor": "cosmic",
        "platform": "linux/amd64/v2",
        "cpu_baseline": "x86-64-v2",
        "hardware_scope": "qemu",
        "resolved_inputs": {
            "source": digest,
            "overlay": "sha256:" + "b" * 64,
            "installer": "sha256:" + "c" * 64,
            "engine": "sha256:" + "d" * 64,
        },
        "browser": {
            "name": "chromium",
            "version": "140.0",
            "memory_gib": 8,
            "free_disk_gib": 20,
        },
        "offline_network_disabled": True,
        "observed": {"plain": record, "encrypted": dict(record)},
        "measurements": {
            "cold": {"duration_s": 60.0},
            "warm": {"duration_s": 12.0},
        },
        "qualifiedAt": "2026-10-17T01:02:03Z",
        "receiptDigest": DIGEST_C,
    }


def test_schema_receipt_without_installed_boot_proof_cannot_score_qualified():
    receipt = _strict_v1_receipt(installed_boot=False)
    document = collector.collect(
        single_variant_config(), SOURCE, lambda _: {"workflow_runs": []},
        now=NOW, receipts={"albacore:cosmic:linux/amd64/v2": receipt},
    )
    intel = next(
        row for row in document["targets"]
        if row["target"]["platform"] == "linux/amd64/v2"
    )
    assert "qualification" not in intel


def test_collect_default_path_shape_unchanged_without_receipts():
    document = collector.collect(
        single_variant_config(), SOURCE, lambda _: {"workflow_runs": []}, now=NOW)
    collector.validate(document, expected_kind="build-health", now=NOW)
    assert all("qualification" not in row for row in document["targets"])


def test_legacy_receipt_without_observations_remains_unqualified():
    document = collector.collect(
        single_variant_config(), SOURCE, lambda _: {"workflow_runs": []},
        now=NOW, receipts={"albacore:cosmic:linux/amd64/v2": v1_receipt()})
    intel = next(row for row in document["targets"]
                 if row["target"]["platform"] == "linux/amd64/v2")
    assert intel["qualification"]["status"] == "unqualified"


def _catalog_with_receipt(receipt, **pins):
    return targets.catalog_snapshot(
        config(),
        descriptors={"albacore:cosmic:linux/amd64/v2": {
            "platformManifestDigest": DIGEST_B,
            "ociPlatform": {"os": "linux", "architecture": "amd64", "variant": "v2"}}},
        overlays={"albacore:cosmic:linux/amd64/v2": {
            "liveOverlayDigest": DIGEST_1, "liveOverlayBaseDigest": DIGEST_B}},
        receipts=[receipt], installer_revision=pins.get("installer", DIGEST_C),
        engine_revision=pins.get("engine", DIGEST_D),
        browser_builds=pins.get("browser_builds", {
            "albacore:cosmic:linux/amd64/v2": catalog_receipt()["build_provenance"]}))


def _candidate_status(snapshot):
    return next(e["qualification"]["status"] for e in snapshot["targets"]
                if e["targetKey"] == "albacore:cosmic:linux/amd64/v2")


def test_strict_raw_and_projected_receipts_have_same_admission():
    receipt = catalog_receipt()
    assert _candidate_status(_catalog_with_receipt(receipt)) == "qualified"
    assert _candidate_status(_catalog_with_receipt(
        targets.receipt_to_catalog_projection(receipt))) == "qualified"


@pytest.mark.parametrize("status", [None, "running", "queued", "skipped", "passed"])
def test_untyped_receipt_status_never_substitutes_for_install_evidence(status):
    assert _candidate_status(_catalog_with_receipt(v1_receipt(status=status))) == "unqualified"


@pytest.mark.parametrize("mutation", [
    lambda r: r.pop("observed"),
    lambda r: r["observed"].pop("encrypted"),
    lambda r: r["observed"]["plain"].update(installed_boot=False),
    lambda r: r["observed"]["encrypted"].update(booted_digest=DIGEST_F),
    lambda r: r.update(status="running"),
    lambda r: r["browser"].update(name="native-qemu"),
    lambda r: r.update(receiptDigest=DIGEST_A),
    lambda r: r["resolved_inputs"].update(engine=DIGEST_E),
    lambda r: r.update(cpu_baseline="wrong"),
])
def test_incomplete_tampered_or_wrong_identity_evidence_is_unqualified(mutation):
    receipt = catalog_receipt()
    mutation(receipt)
    assert _candidate_status(_catalog_with_receipt(receipt)) == "unqualified"


@pytest.mark.parametrize("pins", [
    {"installer": ""}, {"engine": "tacklebox-1.0"},
    {"installer": DIGEST_E}, {"engine": DIGEST_F},
])
def test_independent_expected_revisions_are_required(pins):
    assert _candidate_status(_catalog_with_receipt(catalog_receipt(), **pins)) == "unqualified"


def test_projection_cannot_replace_original_receipt_identity():
    projected = targets.receipt_to_catalog_projection(catalog_receipt())
    projected["_qualificationEvidence"]["resolved_inputs"]["engine"] = DIGEST_E
    assert _candidate_status(_catalog_with_receipt(projected)) == "unqualified"


def test_projection_metadata_is_derived_only_from_original_evidence():
    raw = catalog_receipt()
    projected = targets.receipt_to_catalog_projection(raw)
    projected.update(browser={"name": "forged"}, qualifiedAt="tomorrow",
                     receiptDigest=DIGEST_F, status="passed")
    snapshot = _catalog_with_receipt(projected)
    candidate = next(e for e in snapshot["targets"]
                     if e["targetKey"] == "albacore:cosmic:linux/amd64/v2")
    assert candidate["qualification"]["status"] == "qualified"
    for field in ("browser", "qualifiedAt", "receiptDigest"):
        assert candidate["qualification"][field] == raw[field]


@pytest.mark.parametrize("raw", [None, False, 1, "bad", []])
def test_malformed_original_evidence_is_unqualified(raw):
    projected = targets.receipt_to_catalog_projection(catalog_receipt())
    projected["_qualificationEvidence"] = raw
    assert _candidate_status(_catalog_with_receipt(projected)) == "unqualified"


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["memory_gib", "cold"])
def test_nonfinite_resources_and_measurements_are_rejected(number, field):
    receipt = catalog_receipt()
    if field == "cold":
        receipt["measurements"]["cold"]["duration_s"] = number
    else:
        receipt["browser"][field] = number
    with pytest.raises(ValueError, match="finite"):
        targets._qualification_validator()(receipt, "test")
    assert _candidate_status(_catalog_with_receipt(receipt)) == "unqualified"


def test_real_collector_subprocess_installs_output_limit(tmp_path, monkeypatch):
    import os
    gh = tmp_path / "gh"
    gh.write_text('#!/bin/sh\nprintf \'{"workflow_runs": []}\\n\'\n')
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    assert collector.gh_fetch("repos/tuna-os/tunaOS/actions/runs", "2022-11-28") == {"workflow_runs": []}


@pytest.mark.parametrize("builds", [None, {}, {"albacore:cosmic:linux/amd64/v2": {"origin": "browser"}}])
def test_no_independent_browser_build_provenance_cannot_qualify(builds):
    assert _candidate_status(_catalog_with_receipt(catalog_receipt(), browser_builds=builds)) == "unqualified"


def test_self_asserted_browser_origin_cannot_replace_trusted_artifact_binding():
    expected = copy.deepcopy(catalog_receipt()["build_provenance"])
    expected["iso_digest"] = DIGEST_2
    assert _candidate_status(_catalog_with_receipt(catalog_receipt(), browser_builds={
        "albacore:cosmic:linux/amd64/v2": expected})) == "unqualified"


@pytest.mark.parametrize("field,value", [("name", "unknown"), ("name", " n/a "),
                                         ("version", "unknown"), ("version", "placeholder")])
def test_placeholder_profile_cannot_be_browser_proof(field, value):
    receipt = catalog_receipt()
    receipt["browser"][field] = value
    with pytest.raises(ValueError, match="browser"):
        targets._qualification_validator()(receipt, "test")
    assert _candidate_status(_catalog_with_receipt(receipt)) == "unqualified"


@pytest.mark.parametrize("receipt", [catalog_receipt(), _strict_v1_receipt(), v1_receipt(
    status="qualified", observed={mode: {"installed_boot": True, "desktop_contract": True}
                                  for mode in ("plain", "encrypted")})])
def test_reporting_cannot_admit_self_asserted_or_structural_receipts(receipt):
    projected = targets.receipt_to_catalog_projection(receipt)
    summary = collector._qualification_summary(projected)
    assert summary["status"] == "unqualified"
    assert summary["receiptDigest"] == projected["receiptDigest"]
    assert summary["coldSeconds"] is not None
