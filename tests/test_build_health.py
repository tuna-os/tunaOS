"""INCIDENT-current-health: an old publication hid a failed latest build.

Falsification: failures, skipped gates, absent coverage, mismatched receipts and
old evidence must remain visible even when a previous publication was good.
Fixtures exercise the evaluation boundary; they do not authenticate CI runs.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.contracts import evidence, health, targets
from test_contract_evidence import ATTEMPT, FACTORY, IMAGE, NOW, PUBLICATION, TARGET


def jobs(**conclusions):
    return [{"phase": phase, "status": "completed", "conclusion": conclusions.get(phase, "success")}
            for phase in ("build", "gate", "promote")]


@pytest.mark.parametrize("phase", ["build", "gate", "promote"])
@pytest.mark.parametrize("result", ["failure", "timed_out", "startup_failure"])
def test_failed_required_job_dominates_skipped_downstream_jobs(phase, result):
    observation = jobs(**{phase: result})
    for job in observation:
        if job["phase"] != phase:
            job["conclusion"] = "skipped"
    assert health.attempt_status(observation) == ("failed", [phase + "-failed"])


@pytest.mark.parametrize("result,status", [("cancelled", "blocked"), ("skipped", "blocked"),
                                         ("neutral", "unknown"), (None, "unknown")])
def test_required_gate_cannot_be_replaced_by_promote_success(result, status):
    assert health.attempt_status(jobs(gate=result))[0] == status


def test_duplicate_or_missing_required_jobs_do_not_prove_success():
    assert health.attempt_status(jobs() + [jobs()[0]])[0] == "unknown"
    assert health.attempt_status(jobs()[:2]) == ("missing", ["promote-missing"])
    assert health.attempt_status(jobs()) == ("success", [])


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting", "pending", "requested"])
def test_current_pending_job_remains_running(status):
    observation = jobs()
    observation[1].update(status=status, conclusion=None)
    assert health.attempt_status(observation)[0] == "running"


@pytest.fixture
def observations():
    factory = copy.deepcopy(FACTORY)
    factory["promotionStatus"] = "promoted"
    image = copy.deepcopy(IMAGE)
    image["factoryReceiptDigests"] = ["sha256:" + hashlib.sha256(evidence.canonical_json(factory)).hexdigest()]
    return {"required": {"target": copy.deepcopy(TARGET), "required": True, "scheduled": True},
            "attempt": {"identity": copy.deepcopy(ATTEMPT), "status": "success",
                        "imageDigest": image["imageDigest"], "measuredAt": "2026-10-10T11:00:00Z", "evidence": []},
            "publication": copy.deepcopy(PUBLICATION),
            "package": {"receipt": factory, "measuredAt": "2026-10-10T10:30:00Z",
                        "latestAttempt": {"identity": copy.deepcopy(ATTEMPT), "status": "success",
                                          "measuredAt": "2026-10-10T10:30:00Z"}},
            "image": {"receipt": image, "measuredAt": "2026-10-10T11:00:00Z"}}


def evaluate(observation, **overrides):
    options = {"collection_available": True, "now": NOW, "build_seconds": 172800,
               "required_image_checks": {"boot"}, "required_factory_checks": {"install"},
               "publication_time": "2026-10-10T11:10:00Z"}
    options.update(overrides)
    return health.evaluate_row(**observation, **options)


def test_matching_authenticated_receipts_and_observation_times_are_healthy(observations):
    row = evaluate(observations)
    assert row["status"] == "healthy"
    assert row["measuredAt"] == "2026-10-10T10:30:00Z"
    assert row["reasons"] == []
    assert row["lastVerifiedPublication"] == PUBLICATION
    assert observations["package"]["receipt"]["promotionStatus"] == "promoted"
    feed = {"schemaVersion": 1, "kind": "build-health", "generatedAt": "2026-10-10T12:00:00Z",
            "sourceRevision": ATTEMPT["sourceRevision"], "coverageDigest": IMAGE["imageDigest"],
            "collection": {"status": "available", "sources": [{"id": "images", "repository": "tuna-os/tunaos",
                                                                 "status": "available", "evidence": []}]},
            "freshnessPolicy": {"buildSeconds": 172800, "feedSeconds": 86400}, "targets": [row]}
    assert evidence.validate(feed, "build-health", now=NOW) == feed


@pytest.mark.parametrize("status", ["failed", "blocked", "running", "missing", "stale", "unknown"])
def test_last_good_publication_cannot_hide_latest_result(observations, status):
    observations["attempt"]["status"] = status
    row = evaluate(observations, collection_available=False)
    assert row["status"] == status
    assert row["lastVerifiedPublication"] == PUBLICATION


def test_no_attempt_remains_missing_with_old_publication(observations):
    observations["attempt"] = None
    assert evaluate(observations)["status"] == "missing"


@pytest.mark.parametrize('status', ['failed', 'blocked', 'running', 'stale', 'unknown'])
def test_retained_factory_supply_does_not_hide_latest_factory_attempt(observations, status):
    observations['package']['latestAttempt']['status'] = status
    row = evaluate(observations)
    assert row['packageReadiness']['status'] == status
    assert row['status'] == status
    assert row['packageReadiness']['factoryDigest'] == FACTORY['factoryDigest']


def test_factory_receipt_must_match_the_latest_successful_factory_attempt(observations):
    observations['package']['latestAttempt']['identity']['runAttempt'] += 1
    assert evaluate(observations)['status'] == 'blocked'


def test_incomplete_collection_cannot_report_health(observations):
    assert evaluate(observations, collection_available=False)["status"] == "unknown"


def test_unscheduled_required_target_remains_blocked(observations):
    observations["required"]["scheduled"] = False
    assert evaluate(observations)["status"] == "blocked"


@pytest.mark.parametrize("kind", ["image", "package"])
def test_cross_target_receipts_remain_blocked(observations, kind):
    observations[kind]["receipt"]["target"]["platform"] = "linux/arm64"
    observations[kind]["receipt"]["target"]["cpuBaseline"] = "armv8-a"
    assert evaluate(observations)["status"] == "blocked"


def test_artifact_digest_does_not_substitute_for_receipt_digest(observations):
    observations["image"]["receipt"]["factoryReceiptDigests"] = [observations["package"]["receipt"]["factoryDigest"]]
    assert evaluate(observations)["status"] == "blocked"


def test_wrong_attempt_identity_does_not_substitute_for_latest_receipt(observations):
    observations["attempt"]["identity"]["runAttempt"] += 1
    assert evaluate(observations)["status"] == "blocked"


@pytest.mark.parametrize("status", ["pending", "blocked", "failed"])
def test_unpromoted_package_supply_is_not_healthy(observations, status):
    observations["package"]["receipt"]["promotionStatus"] = status
    assert evaluate(observations)["status"] == ("failed" if status == "failed" else "blocked")


def test_self_declared_passing_subset_cannot_remove_required_checks(observations):
    assert evaluate(observations, required_image_checks={"boot", "installed-contract"})["status"] == "blocked"
    assert evaluate(observations, required_factory_checks={"install", "signature", "cpu-baseline"})["status"] == "blocked"


@pytest.mark.parametrize("kind", ["image", "package"])
def test_generating_a_fresh_feed_does_not_refresh_old_evidence(observations, kind):
    observations[kind]["measuredAt"] = "2026-10-07T10:00:00Z"
    assert evaluate(observations)["status"] == "stale"


@pytest.mark.parametrize("measured", [None, "2026-10-11T10:00:00Z", "2026-10-10T10:00:00+00:00"])
def test_missing_future_or_noncanonical_evidence_time_is_unknown(observations, measured):
    observations["package"]["measuredAt"] = measured
    assert evaluate(observations)["status"] == "unknown"


def test_required_coverage_is_preserved_without_observations():
    root = Path(__file__).resolve().parents[1]
    records = targets.resolve_required_targets(yaml.safe_load((root / '.github/build-config.yml').read_text()))
    rows = [health.evaluate_row(record, None, None, None, None, collection_available=False,
                               now=NOW, build_seconds=172800, required_image_checks={"boot"},
                               required_factory_checks={"install"}) for record in records]
    assert len(rows) == len(records) == 269
    assert {targets.target_key(row["target"]) for row in rows} == {targets.target_key(row["target"]) for row in records}
    assert all(row["required"] and row["status"] == "missing" for row in rows)
