"""Optional schema fields must still establish linkage before health is green."""
import copy
import datetime as dt
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from contracts.evidence import canonical_json, validate
from contracts.health import evaluate_row

NOW = dt.datetime(2026, 10, 19, 21, tzinfo=dt.timezone.utc)
STAMP = "2026-10-19T20:59:00Z"


def digest(char):
    return "sha256:" + char * 64


def inputs():
    target = {"variant": "yellowfin", "flavor": "gnome", "platform": "linux/amd64/v2",
              "cpuBaseline": "x86-64-v2", "hardwareScope": "generic"}
    attempt = {"repository": "tuna-os/tunaos", "workflow": "build.yml", "runId": 1,
               "runAttempt": 1, "sourceRevision": "a" * 40, "startedAt": STAMP}
    evidence = {"url": "https://example.org/proof", "digest": digest("e")}
    common = {"schemaVersion": 1, "target": target, "attemptIdentity": attempt,
              "baseDigest": digest("b"), "contractDigest": digest("c"),
              "checks": [{"name": "contract", "status": "pass", "evidence": [evidence]}],
              "provenance": {"sourceRevision": "a" * 40, "buildrootDigest": digest("d"),
                             "sourceArtifacts": [evidence], "buildrootInventory": [],
                             "compilerFlags": [], "evidence": [evidence]}}
    factory = copy.deepcopy(common)
    factory.update(kind="factory-receipt", factoryDigest=digest("f"), promotionStatus="promoted",
                   publication={"repository": "ghcr.io/tuna-os/factory", "tag": "latest",
                                "digest": digest("f"), "evidence": [evidence["url"]]})
    image = copy.deepcopy(common)
    image.update(kind="image-receipt", imageDigest=digest("a"), sourceRevision="a" * 40,
                 installedPackages=[], publication={"repository": "ghcr.io/tuna-os/yellowfin",
                 "tag": "gnome", "digest": digest("a"), "evidence": [evidence["url"]]})
    image["factoryReceiptDigests"] = ["sha256:" + hashlib.sha256(canonical_json(factory)).hexdigest()]
    return {"required": {"target": target, "required": True, "scheduled": True,
                         "publication": image["publication"], "factoryPublication": factory["publication"]},
            "attempt": {"identity": attempt, "status": "success", "imageDigest": digest("a"), "measuredAt": STAMP},
            "publication": image["publication"], "publication_time": STAMP,
            "package": {"receipt": factory, "measuredAt": STAMP,
                        "latestAttempt": {"identity": attempt, "status": "success", "measuredAt": STAMP}},
            "image": {"receipt": image, "measuredAt": STAMP},
            "collection_available": True, "now": NOW, "build_seconds": 3600,
            "required_image_checks": {"contract"}, "required_factory_checks": {"contract"}}


def validate_receipts(data):
    validate(data["image"]["receipt"], "image-receipt", now=NOW)
    validate(data["package"]["receipt"], "factory-receipt", now=NOW)


def test_complete_schema_valid_receipts_are_healthy():
    data = inputs()
    validate_receipts(data)
    assert evaluate_row(**data)["status"] == "healthy"


@pytest.mark.parametrize("missing", [
    (("image", "baseDigest"),),
    (("package", "baseDigest"),),
    (("image", "baseDigest"), ("package", "baseDigest")),
    (("image", "factoryReceiptDigests"),),
])
def test_schema_valid_missing_linkage_is_blocked(missing):
    data = inputs()
    for receipt, field in missing:
        del data[receipt]["receipt"][field]
    validate_receipts(data)
    result = evaluate_row(**data)
    assert result["status"] == "blocked"
    assert result["reasons"] == ["attempt-publication-receipt-mismatch"]


def test_schema_valid_empty_factory_linkage_is_blocked():
    data = inputs()
    data["image"]["receipt"]["factoryReceiptDigests"] = []
    validate_receipts(data)
    assert evaluate_row(**data)["status"] == "blocked"


@pytest.mark.parametrize("receipt,field,value", [
    ("image", "baseDigest", ""), ("package", "baseDigest", ""),
    ("image", "factoryReceiptDigests", None),
])
def test_schema_invalid_empty_linkage_is_blocked(receipt, field, value):
    data = inputs()
    data[receipt]["receipt"][field] = value
    result = evaluate_row(**data)
    assert result["status"] == "blocked"
    assert result["reasons"] == ["invalid-or-mismatched-receipt"]
