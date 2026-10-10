"""Evaluate current health from observations authenticated by the collector.

This module does not fetch or authenticate receipts. The collector must verify
producer identity and signatures before supplying receipt observations. Missing
or rejected evidence stays absent. Generating a feed cannot refresh evidence.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from copy import deepcopy
from typing import Any

from .evidence import EvidenceError, canonical_json, validate
from .targets import target_key

PHASES = frozenset({"build", "gate", "promote"})


def attempt_status(jobs: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Jobs must already belong to one exact target, source, run and attempt."""
    if not isinstance(jobs, list):
        return "unknown", ["invalid-job-observation"]
    indexed = {}
    for job in jobs:
        if not isinstance(job, dict) or job.get("phase") not in PHASES:
            return "unknown", ["invalid-job-phase"]
        phase = job["phase"]
        if phase in indexed:
            return "unknown", ["ambiguous-job-phase"]
        indexed[phase] = job
    # A failed build with a skipped downstream gate is still a failed attempt.
    failed = sorted(phase for phase, job in indexed.items()
                    if job.get("conclusion") in {"failure", "timed_out", "startup_failure"})
    if failed:
        return "failed", [phase + "-failed" for phase in failed]
    cancelled = sorted(phase for phase, job in indexed.items() if job.get("conclusion") == "cancelled")
    if cancelled:
        return "blocked", [phase + "-cancelled" for phase in cancelled]
    if any(job.get("status") in {"queued", "in_progress", "waiting", "pending", "requested"}
           for job in indexed.values()):
        return "running", ["attempt-in-progress"]
    missing = PHASES - indexed.keys()
    if missing:
        return "missing", [phase + "-missing" for phase in sorted(missing)]
    skipped = sorted(phase for phase, job in indexed.items() if job.get("conclusion") == "skipped")
    if skipped:
        return "blocked", [phase + "-skipped" for phase in skipped]
    if any(job.get("status") != "completed" or job.get("conclusion") != "success"
           for job in indexed.values()):
        return "unknown", ["unrecognized-job-result"]
    return "success", []


def timestamp(value: str, now: dt.datetime) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError("health observations require UTC timestamps")
    try:
        measured = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise EvidenceError("invalid health timestamp") from exc
    if measured > now:
        raise EvidenceError("health observation is in the future")
    return measured


def evaluate_row(required: dict[str, Any], attempt: dict | None,
                 publication: dict | None, package: dict | None,
                 image: dict | None, *, collection_available: bool,
                 now: dt.datetime, build_seconds: int,
                 required_image_checks: set[str], required_factory_checks: set[str],
                 publication_time: str | None = None) -> dict:
    """Keep last good publication separate from the latest attempt's result.

    `image` and `package` contain receipts authenticated by the collector and
    measuredAt from their authenticated producer observations. Receipt digests
    are computed from canonical bytes. Required checks come from the consumer
    contract, never the receipt's own list.
    Structural validation below also rejects cross-target and cross-attempt
    mixing. No boolean field inside a receipt establishes producer trust.
    """
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise EvidenceError("health evaluation requires UTC")
    if type(build_seconds) is not int or build_seconds < 1:
        raise EvidenceError("invalid build freshness policy")
    if not required_image_checks or not required_factory_checks:
        raise EvidenceError("required contract checks cannot be empty")
    image_observation, package_observation = image, package
    image = image.get("receipt") if isinstance(image, dict) else None
    package = package.get("receipt") if isinstance(package, dict) else None
    target = required["target"]
    target_key(target)
    readiness = {"status": "missing", "measuredAt": None, "evidence": []}
    contract = "missing"
    reasons = []
    row = {"target": deepcopy(target), "required": required["required"],
           "scheduled": required["scheduled"], "latestAttempt": deepcopy(attempt),
           "lastVerifiedPublication": deepcopy(publication), "packageReadiness": readiness,
           "contractStatus": contract, "status": "missing", "reasons": reasons,
           "measuredAt": None}
    receipt_error = None
    for receipt, kind in ((image, "image-receipt"), (package, "factory-receipt")):
        if receipt is None:
            continue
        try:
            validate(receipt, kind, now=now)
            if receipt["target"] != target:
                raise EvidenceError("receipt target differs from required target")
        except (EvidenceError, KeyError, TypeError, ValueError):
            receipt_error = "invalid-or-mismatched-receipt"
    if receipt_error:
        image = package = None
        contract = "blocked"
    if package is not None:
        checks = package["checks"]
        statuses = {check["status"] for check in checks}
        package_status = ("failed" if "fail" in statuses or package["promotionStatus"] == "failed" else
                          "healthy" if statuses == {"pass"} and package["promotionStatus"] == "promoted"
                          and required_factory_checks <= {check["name"] for check in checks} else "blocked")
        readiness.update(status=package_status, measuredAt=package_observation.get("measuredAt"),
                         factoryDigest=package["factoryDigest"], contractDigest=package["contractDigest"])
        readiness["evidence"] = [item for check in checks for item in check["evidence"]]
    if image is not None:
        checks = image["checks"]
        statuses = {check["status"] for check in checks}
        contract = ("fail" if "fail" in statuses else "pass" if statuses == {"pass"}
                    and required_image_checks <= {check["name"] for check in checks} else "blocked")
    row["contractStatus"] = contract
    if attempt is None:
        reasons.append("required-attempt-missing")
        return row
    status = attempt.get("status")
    if status != "success":
        row["status"] = status if status in {"running", "failed", "blocked", "missing", "stale", "unknown"} else "unknown"
        reasons.append("latest-attempt-" + row["status"])
        return row
    if not collection_available:
        row["status"] = "unknown"
        reasons.append("collection-unavailable")
        return row
    if not required["scheduled"]:
        row["status"] = "blocked"
        reasons.append("required-target-unscheduled")
        return row
    if receipt_error:
        row["status"] = "blocked"
        reasons.append(receipt_error)
        return row
    if readiness["status"] != "healthy" or contract != "pass":
        row["status"] = "failed" if readiness["status"] == "failed" or contract == "fail" else "blocked"
        reasons.append("package-or-image-contract-" + row["status"])
        return row
    if (publication is None or not attempt.get("imageDigest")
        or publication["digest"] != attempt["imageDigest"]
        or image["imageDigest"] != attempt["imageDigest"]
        or image["attemptIdentity"] != attempt["identity"]
        or image["contractDigest"] != package["contractDigest"]
        or image["baseDigest"] != package["baseDigest"]
        or "sha256:" + hashlib.sha256(canonical_json(package)).hexdigest() not in image["factoryReceiptDigests"]):
        row["status"] = "blocked"
        reasons.append("attempt-publication-receipt-mismatch")
        return row
    try:
        times = [timestamp(item, now) for item in
                 (attempt["measuredAt"], publication_time,
                  image_observation.get("measuredAt"), package_observation.get("measuredAt"))]
    except (EvidenceError, KeyError):
        row["status"] = "unknown"
        reasons.append("invalid-evidence-time")
        return row
    oldest = min(times)
    row["measuredAt"] = oldest.isoformat().replace("+00:00", "Z")
    if (now - oldest).total_seconds() > build_seconds:
        row["status"] = "stale"
        reasons.append("evidence-exceeds-build-freshness")
        return row
    row["status"] = "healthy"
    return row
