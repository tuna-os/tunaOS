"""Versioned evidence keeps target identity and structural proof unambiguous."""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import socket
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.contracts import evidence

NOW = dt.datetime(2026, 10, 10, 12, tzinfo=dt.timezone.utc)
TARGET = {"variant": "yellowfin", "flavor": "cosmic", "platform": "linux/amd64/v2",
          "cpuBaseline": "x86-64-v2", "hardwareScope": "generic"}
DIGEST = "sha256:" + "2" * 64
REVISION = "1" * 40
ATTEMPT = {"repository": "tuna-os/tunaos", "workflow": "build.yml", "runId": 42,
           "runAttempt": 2, "sourceRevision": REVISION, "startedAt": "2026-10-10T10:00:00Z"}
PUBLICATION = {"repository": "ghcr.io/tuna-os/yellowfin", "digest": DIGEST,
               "evidence": ["https://github.com/tuna-os/tunaos/actions/runs/42"]}
PROVENANCE = {"sourceRevision": REVISION, "buildrootDigest": DIGEST,
              "sourceArtifacts": [{"url": "https://example.org/source.tar.gz", "digest": DIGEST}], "buildrootInventory": [], "compilerFlags": [], "evidence": []}
CONSUMER = {"schemaVersion": 1, "kind": "consumer-contract", "target": TARGET,
            "sourceRevision": REVISION,
            "contractDigest": "sha256:d194c62e74bbfa6efc82afb2557bce15e2bcaa7ee9cac191ccbfc471433361a7",
            "baseDigest": DIGEST, "packageManager": "dnf",
            "baseReference": "ghcr.io/tuna-os/yellowfin-base@" + DIGEST, "packageRequirements": [{"name": "cosmic-session"}],
            "approvedSources": [{"id": "factory", "url": "https://packages.tunaos.org/el10",
                                 "signingIdentity": "tunaos-factory"}], "requiredChecks": ["install"]}
FACTORY = {"schemaVersion": 1, "kind": "factory-receipt", "target": TARGET,
           "contractDigest": CONSUMER["contractDigest"], "baseDigest": DIGEST,
           "attemptIdentity": ATTEMPT, "checks": [{"name": "install", "status": "pass", "evidence": [{"url": "https://example.org/check.json", "digest": DIGEST}]}],
           "factoryDigest": DIGEST, "inventory": [{"name": "cosmic-session", "version": "1.0-1",
                                                   "architecture": "x86_64", "digest": DIGEST}],
           "provenance": PROVENANCE, "publication": PUBLICATION, "promotionStatus": "pending"}
IMAGE = {"schemaVersion": 1, "kind": "image-receipt", "target": TARGET,
         "contractDigest": CONSUMER["contractDigest"], "baseDigest": DIGEST,
         "attemptIdentity": ATTEMPT, "checks": [{"name": "boot", "status": "pass", "evidence": [{"url": "https://example.org/check.json", "digest": DIGEST}]}],
         "imageDigest": DIGEST, "factoryReceiptDigests": [DIGEST], "sourceRevision": REVISION,
         "installedPackages": [{"name": "cosmic-session", "version": "1.0-1", "architecture": "x86_64", "digest": DIGEST}],
         "publication": PUBLICATION,
         "provenance": PROVENANCE}
HEALTH = {"schemaVersion": 1, "kind": "build-health", "generatedAt": "2026-10-10T11:00:00Z",
          "sourceRevision": REVISION, "coverageDigest": DIGEST,
          "collection": {"status": "degraded", "sources": [{"id": "images", "repository": "tuna-os/tunaos",
                                                            "status": "unavailable", "evidence": []}]},
          "freshnessPolicy": {"buildSeconds": 86400, "feedSeconds": 86400},
          "targets": [{"target": TARGET, "required": True, "scheduled": False, "latestAttempt": None,
                       "lastVerifiedPublication": None, "packageReadiness": {"status": "missing",
                       "factoryDigest": None, "contractDigest": None, "measuredAt": None, "evidence": []},
                       "contractStatus": "missing", "status": "missing", "reasons": ["No evidence"]}]}
DOCUMENTS = [CONSUMER, FACTORY, IMAGE, HEALTH]


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda d: d["kind"])
def test_minimal_documents_load_offline(tmp_path, monkeypatch, document):
    def deny_network(*args, **kwargs):
        pytest.fail("schema validation attempted network access")
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(document))
    assert evidence.load(path, document["kind"], now=NOW) == document


@pytest.mark.parametrize("text", ['{"kind":"image-receipt","kind":"build-health"}',
                                  '{"nested":{"runId":42,"runId":43}}'])
def test_duplicate_json_keys_are_rejected(text):
    with pytest.raises(evidence.EvidenceError, match="duplicate JSON key"):
        evidence.loads(text)


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda d: d["kind"])
@pytest.mark.parametrize("change", [{"schemaVersion": 2}, {"schemaVersion": True},
                                   {"schemaVersion": 1.0}, {"unrecognised": "field"}])
def test_versions_and_unknown_fields_fail_closed(document, change):
    candidate = copy.deepcopy(document)
    candidate.update(change)
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, now=NOW)


@pytest.mark.parametrize("field", ["runId", "runAttempt"])
@pytest.mark.parametrize("value", [True, False, 42.0, 0, -1, "42"])
def test_attempt_ids_are_positive_json_integers(field, value):
    candidate = copy.deepcopy(IMAGE)
    candidate["attemptIdentity"][field] = value
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, now=NOW)


@pytest.mark.parametrize("field,value", [("sourceRevision", "abc123"), ("sourceRevision", "A" * 40),
                                        ("baseDigest", "sha256:abcd"), ("baseDigest", "sha256:" + "A" * 64),
                                        ("baseDigest", "sha512:" + "2" * 64)])
def test_commit_and_artifact_identities_are_full_and_canonical(field, value):
    candidate = copy.deepcopy(CONSUMER)
    candidate[field] = value
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, now=NOW)


def test_consumer_hash_is_canonical_and_detects_changed_content():
    assert evidence.contract_digest(CONSUMER) == "sha256:d194c62e74bbfa6efc82afb2557bce15e2bcaa7ee9cac191ccbfc471433361a7"
    reordered = dict(reversed(list(CONSUMER.items())))
    assert evidence.validate(reordered, now=NOW) == CONSUMER
    candidate = copy.deepcopy(CONSUMER)
    candidate["packageRequirements"][0]["name"] = "different-package"
    with pytest.raises(evidence.EvidenceError, match="digest does not match"):
        evidence.validate(candidate, now=NOW)


@pytest.mark.parametrize("document,path", [(CONSUMER, ["packageRequirements"]), (CONSUMER, ["approvedSources"]),
                                         (CONSUMER, ["requiredChecks"]), (FACTORY, ["checks"]),
                                         (FACTORY, ["inventory"]), (IMAGE, ["installedPackages"]), (HEALTH, ["targets"]),
                                         (HEALTH, ["collection", "sources"])])
def test_duplicate_named_evidence_is_rejected(document, path):
    candidate = copy.deepcopy(document)
    items = candidate
    for key in path:
        items = items[key]
    items.append(copy.deepcopy(items[0]))
    with pytest.raises(evidence.EvidenceError, match="duplicate"):
        evidence.validate(candidate, now=NOW)


@pytest.mark.parametrize("timestamp", ["2026-02-30T10:00:00Z", "2026-10-10T10:00:00+00:00",
                                      "2026-10-10T10:00:00", "2026-10-10T10:00:00-01:00",
                                      "2026-10-10T12:00:01Z"])
@pytest.mark.parametrize("document,path", [(IMAGE, ["attemptIdentity", "startedAt"]),
                                         (HEALTH, ["generatedAt"])])
def test_timestamps_are_real_utc_and_not_future(document, path, timestamp):
    candidate = copy.deepcopy(document)
    parent = candidate
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = timestamp
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, now=NOW)


def test_validation_clock_requires_utc():
    with pytest.raises(evidence.EvidenceError, match="validation time must be UTC"):
        evidence.validate(IMAGE, now=dt.datetime(2026, 10, 10, 12))


def test_alma_t2_v2_and_arm64_identities_are_valid():
    target = dict(TARGET, flavor="cosmic-t2", hardwareScope="apple-t2")
    assert evidence.validate_target(target) is None
    assert evidence.validate_target(dict(TARGET, platform="linux/arm64", cpuBaseline="armv8-a")) is None
    assert FACTORY["inventory"][0]["architecture"] == "x86_64"
    assert evidence.validate(FACTORY, now=NOW)["target"]["platform"] == "linux/amd64/v2"


@pytest.mark.parametrize("change", [{"variant": "skipjack"}, {"cpuBaseline": "x86-64"},
                                   {"hardwareScope": "apple-t2"}, {"platform": "x86_64"},
                                   {"flavor": "cosmic-asahi", "hardwareScope": "apple-silicon"},
                                   {"flavor": "cosmic-t2", "hardwareScope": "apple-t2",
                                    "platform": "linux/arm64", "cpuBaseline": "armv8-a"}])
def test_inconsistent_target_identities_are_rejected(change):
    candidate = dict(TARGET, **change)
    with pytest.raises(evidence.EvidenceError):
        evidence.validate_target(candidate)


def test_missing_health_proof_remains_explicit_and_missing():
    result = evidence.validate(copy.deepcopy(HEALTH), now=NOW)
    row = result["targets"][0]
    assert row["latestAttempt"] is None
    assert row["lastVerifiedPublication"] is None
    assert row["status"] == "missing"
    assert row["packageReadiness"]["status"] == "missing"
    assert row["packageReadiness"]["measuredAt"] is None
    candidate = copy.deepcopy(HEALTH)
    del candidate["targets"][0]["latestAttempt"]
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, now=NOW)


def test_kind_cannot_be_used_as_another_receipt_type():
    with pytest.raises(evidence.EvidenceError, match="unexpected evidence kind"):
        evidence.validate(FACTORY, "image-receipt", now=NOW)


HEALTHY = {
    "schemaVersion": 1, "kind": "build-health", "generatedAt": "2026-10-10T11:00:00Z",
    "sourceRevision": REVISION, "coverageDigest": DIGEST,
    "collection": {"status": "available", "sources": [{"id": "images", "repository": "tuna-os/tunaos",
                                                        "status": "available", "evidence": []}]},
    "freshnessPolicy": {"buildSeconds": 86400, "feedSeconds": 86400},
    "targets": [{"target": TARGET, "required": True, "scheduled": True,
                 "latestAttempt": {"identity": ATTEMPT, "status": "success", "imageDigest": DIGEST,
                                   "measuredAt": "2026-10-10T11:00:00Z", "evidence": []},
                 "lastVerifiedPublication": PUBLICATION,
                 "packageReadiness": {"status": "healthy", "factoryDigest": DIGEST,
                                      "contractDigest": CONSUMER["contractDigest"],
                                      "measuredAt": "2026-10-10T11:00:00Z", "evidence": []},
                 "contractStatus": "pass", "status": "healthy", "reasons": [],
                 "measuredAt": "2026-10-10T11:00:00Z"}],
}


def test_internally_consistent_healthy_feed_loads(tmp_path):
    path = tmp_path / "healthy.json"
    path.write_text(json.dumps(HEALTHY))
    assert evidence.load(path, "build-health", now=NOW) == HEALTHY


@pytest.mark.parametrize("path,value", [
    (["collection", "status"], "degraded"),
    (["collection", "sources", 0, "status"], "unavailable"),
    (["targets", 0, "required"], False),
    (["targets", 0, "scheduled"], False),
    (["targets", 0, "latestAttempt"], None),
    (["targets", 0, "latestAttempt", "status"], "failed"),
    (["targets", 0, "latestAttempt", "imageDigest"], None),
    (["targets", 0, "latestAttempt", "measuredAt"], None),
    (["targets", 0, "lastVerifiedPublication"], None),
    (["targets", 0, "lastVerifiedPublication", "digest"], "sha256:" + "3" * 64),
    (["targets", 0, "packageReadiness", "status"], "missing"),
    (["targets", 0, "packageReadiness", "measuredAt"], None),
    (["targets", 0, "contractStatus"], "missing"),
    (["targets", 0, "measuredAt"], None),
])
def test_healthy_feed_rejects_missing_or_contradictory_inputs(path, value):
    candidate = copy.deepcopy(HEALTHY)
    parent = candidate
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, now=NOW)


@pytest.mark.parametrize("status", ["missing", "unknown"])
def test_unproven_health_states_allow_explicit_nulls(status):
    candidate = copy.deepcopy(HEALTH)
    candidate["targets"][0]["status"] = status
    candidate["targets"][0]["packageReadiness"]["status"] = status
    candidate["targets"][0]["contractStatus"] = status
    assert evidence.validate(candidate, now=NOW) == candidate


@pytest.mark.parametrize("document,field", [(CONSUMER, "packageManager"), (CONSUMER, "baseReference"),
                                         (IMAGE, "sourceRevision"), (IMAGE, "installedPackages"),
                                         (IMAGE, "factoryReceiptDigests")])
def test_new_contract_identity_fields_are_mandatory(document, field):
    candidate = copy.deepcopy(document)
    del candidate[field]
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, now=NOW)


@pytest.mark.parametrize("reference", ["ghcr.io/tuna-os/base:latest", "ghcr.io/tuna-os/base@sha256:abc",
                                      "ghcr.io/tuna-os/base@sha256:" + "3" * 64])
def test_base_reference_must_pin_the_declared_base_digest(reference):
    candidate = copy.deepcopy(CONSUMER)
    candidate["baseReference"] = reference
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, verify_digest=False, now=NOW)


@pytest.mark.parametrize("document", [FACTORY, IMAGE], ids=lambda d: d["kind"])
@pytest.mark.parametrize("path,value", [(["checks", 0, "evidence"], []),
                                      (["checks", 0, "evidence"], [{"url": "https://example.org/check"}]),
                                      (["provenance", "sourceArtifacts"], []),
                                      (["provenance", "sourceArtifacts"], [{"url": "https://example.org/source"}]),
                                      (["publication", "digest"], "sha256:" + "3" * 64),
                                      (["attemptIdentity", "sourceRevision"], "3" * 40),
                                      (["provenance", "sourceRevision"], "3" * 40)])
def test_receipts_require_immutable_proof_and_consistent_identity(document, path, value):
    candidate = copy.deepcopy(document)
    parent = candidate
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, now=NOW)


@pytest.mark.parametrize("field,value", [("sourceRevision", "3" * 40), ("installedPackages", []),
                                        ("factoryReceiptDigests", [DIGEST, DIGEST]),
                                        ("factoryDigest", DIGEST)])
def test_image_receipt_rejects_incomplete_or_obsolete_factory_links(field, value):
    candidate = copy.deepcopy(IMAGE)
    candidate[field] = value
    with pytest.raises(evidence.EvidenceError):
        evidence.validate(candidate, now=NOW)
