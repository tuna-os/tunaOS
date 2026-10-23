#!/usr/bin/env python3
"""Bounded public GitHub observations; successful jobs are never receipt proof.

The caller supplies the centrally pinned API version. No token or API error body
is persisted. This collector intentionally cannot produce a healthy publication
until a separately authenticated receipt collector is connected.
"""
from __future__ import annotations

import argparse
import json
import re
import resource
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from contracts.health import attempt_status, evaluate_row
from contracts.evidence import validate
from contracts.targets import coverage_document, platform_slug

REPOSITORY = "tuna-os/tunaOS"
RUN_DEPTH = 200
FETCH_DEPTH = RUN_DEPTH * 4
MAX_BYTES = 8 * 1024 * 1024
MAX_JOB_PAGES = 20
SHA = re.compile(r"[0-9a-f]{40}\Z")
WRAPPERS = {
    "albacore": "🐟-albacore", "yellowfin": "🐠-yellowfin",
    "skipjack": "🍣-skipjack", "wahoo": "🎏-wahoo", "bonito": "🎣-bonito",
    "hummingbird": "🐦-hummingbird", "sailfin": "⛵-sailfin", "guppy": "🌈-guppy",
    "bonito-rawhide": "🐉-bonito-rawhide", "gurnard": "🤖-gurnard",
    "grouper": "🪸-grouper", "marlin": "🚀-marlin", "flounder": "🐡-flounder",
    "flounder-sid": "☢️-flounder-sid",
}


class CollectionError(ValueError):
    """An unavailable/malformed API observation, never an empty observation."""


def strict_json(raw: bytes):
    if len(raw) > MAX_BYTES:
        raise CollectionError("API response exceeds bound")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CollectionError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise CollectionError("nonfinite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CollectionError("invalid API JSON") from exc


def positive_int(value):
    if type(value) is not int or value < 1:
        raise CollectionError("invalid API integer identity")
    return value


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise CollectionError("invalid API UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise CollectionError("invalid API UTC timestamp") from exc


def gh_fetch(endpoint: str, api_version: str):
    if not re.fullmatch(r"\d{4}-\d\d-\d\d", api_version):
        raise CollectionError("explicit API version is invalid")
    if not endpoint.startswith(f"repos/{REPOSITORY}/actions/") or any(c in endpoint for c in "\r\n"):
        raise CollectionError("API endpoint outside collector scope")
    try:
        # File output bounds memory and avoids recording credentials/error bodies.
        import tempfile
        with tempfile.TemporaryFile() as output:
            def bound_output():
                resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
            result = subprocess.run(
                ["gh", "api", "--hostname", "github.com", endpoint,
                 "-H", f"X-GitHub-Api-Version: {api_version}"],
                stdout=output, stderr=subprocess.DEVNULL, timeout=60, check=False,
                preexec_fn=bound_output,
            )
            if result.returncode:
                raise CollectionError("GitHub API unavailable")
            output.seek(0)
            return strict_json(output.read(MAX_BYTES + 1))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectionError("GitHub API unavailable") from exc


def main_run(run: dict, workflow: str):
    if not isinstance(run, dict):
        raise CollectionError("invalid workflow run")
    head = run.get("head_repository")
    repository = run.get("repository")
    if not isinstance(head, dict) or not isinstance(repository, dict):
        raise CollectionError("missing run repository identity")
    if (head.get("full_name") != REPOSITORY or head.get("fork") is not False
            or repository.get("full_name") != REPOSITORY or repository.get("private") is not False
            or run.get("head_branch") != "main" or run.get("event") == "pull_request"
            or run.get("path") != f".github/workflows/{workflow}"):
        raise CollectionError("run outside public main nonfork workflow policy")
    positive_int(run.get("id"))
    positive_int(run.get("run_attempt"))
    if not isinstance(run.get("head_sha"), str) or not SHA.fullmatch(run["head_sha"]):
        raise CollectionError("invalid run source revision")
    timestamp(run.get("run_started_at"))
    if run.get("status") not in {"queued", "in_progress", "completed", "waiting", "pending", "requested"}:
        raise CollectionError("unknown run status")
    return run


def fetch_runs(fetch: Callable, workflow: str):
    runs = []
    seen = set()
    for page in range(1, FETCH_DEPTH // 100 + 1):
        body = fetch(f"repos/{REPOSITORY}/actions/workflows/{workflow}/runs?branch=main&per_page=100&page={page}")
        if not isinstance(body, dict) or not isinstance(body.get("workflow_runs"), list):
            raise CollectionError("malformed run list")
        page_runs = body["workflow_runs"]
        if len(page_runs) > 100:
            raise CollectionError("oversized run page")
        for item in page_runs:
            run = main_run(item, workflow)
            if run["id"] in seen:
                raise CollectionError("duplicate workflow run across pages")
            seen.add(run["id"])
            runs.append(run)
        if len(page_runs) < 100:
            break
    # Sort rather than trust API page ordering. Attempts never merge across runs.
    return sorted(runs, key=lambda r: (timestamp(r["run_started_at"]), r["id"]), reverse=True)


def fetch_jobs(fetch: Callable, run: dict):
    jobs = []
    seen = set()
    total = None
    for page in range(1, MAX_JOB_PAGES + 1):
        endpoint = (f"repos/{REPOSITORY}/actions/runs/{run['id']}/attempts/"
                    f"{run['run_attempt']}/jobs?per_page=100&page={page}")
        body = fetch(endpoint)
        if not isinstance(body, dict) or not isinstance(body.get("jobs"), list):
            raise CollectionError("malformed job list")
        count = body.get("total_count")
        if type(count) is not int or count < 0 or count > MAX_JOB_PAGES * 100:
            raise CollectionError("job count exceeds bound")
        if total is not None and count != total:
            raise CollectionError("job pagination changed during collection")
        total = count
        if len(body["jobs"]) > 100:
            raise CollectionError("oversized jobs page")
        for job in body["jobs"]:
            if not isinstance(job, dict):
                raise CollectionError("malformed job")
            identity = positive_int(job.get("id"))
            positive_int(job.get("run_id"))
            positive_int(job.get("run_attempt"))
            if identity in seen or job.get("run_id") != run["id"] or job.get("run_attempt") != run["run_attempt"]:
                raise CollectionError("job attempt identity mismatch or duplicate")
            if job.get("head_sha") != run["head_sha"]:
                raise CollectionError("job source identity mismatch")
            if job.get("head_branch") != "main":
                raise CollectionError("job branch identity mismatch")
            if not isinstance(job.get("name"), str):
                raise CollectionError("missing job display name")
            seen.add(identity)
            jobs.append(job)
        if len(jobs) == total:
            return jobs
        if len(body["jobs"]) < 100:
            raise CollectionError("incomplete job pagination")
    raise CollectionError("job pagination exhausted")


def normalized_jobs(jobs: list[dict], target: dict):
    """Exact suffixes preserve full OCI platform; global gates apply per flavor.

    The wrapper name is authored by build-<variant>.yml. Unknown names for a
    known flavor explicitly poison that observation instead of silently dropping
    a failed build. Known ancillary jobs remain outside these three phases.
    """
    wrapper = WRAPPERS.get(target['variant'])
    if wrapper is None:
        raise CollectionError("unknown workflow wrapper")
    prefix = f"{wrapper} / {target['flavor']} / "
    phases = {platform_slug(target["platform"]): "build", "Gate": "gate", "Promote": "promote"}
    ancillary = {"Manifest", "Sign", "Asahi manifest gate", "Desktop contract",
                 "Attest SBOM", "SBOM", "Scan", "Prune"}
    platforms = {"linux-amd64", "linux-amd64-v2", "linux-arm64"}
    normalized = []
    for job in jobs:
        name = job["name"]
        if not name.startswith(prefix):
            if f" / {target['flavor']} / " in name:
                normalized.append({"phase": "unknown", "status": job.get("status"),
                                   "conclusion": job.get("conclusion")})
            continue
        suffix = name[len(prefix):]
        if suffix in phases:
            normalized.append({"phase": phases[suffix], "status": job.get("status"),
                               "conclusion": job.get("conclusion")})
        elif suffix not in ancillary | platforms:
            normalized.append({"phase": "unknown", "status": job.get("status"),
                               "conclusion": job.get("conclusion")})
    return normalized


def collect(config: dict, source_revision: str, fetch: Callable, *, now=None,
            build_seconds=172800, feed_seconds=3600):
    if not isinstance(source_revision, str) or not SHA.fullmatch(source_revision):
        raise CollectionError("collector source revision must be immutable")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo != timezone.utc:
        raise CollectionError("collector clock must be UTC")
    coverage = coverage_document(config)
    rows = coverage["targets"]
    found = {}
    sources = []
    for variant in sorted({r["target"]["variant"] for r in rows}):
        workflow = f"build-{variant}.yml"
        available = True
        try:
            runs = fetch_runs(fetch, workflow)
            walked = 0
            for run in runs:
                if timestamp(run["run_started_at"]) > now:
                    raise CollectionError("future run timestamp")
                if run["status"] == "completed":
                    if walked >= RUN_DEPTH:
                        break
                    walked += 1
                jobs = fetch_jobs(fetch, run)
                for row in rows:
                    target = row["target"]
                    if target["variant"] != variant:
                        continue
                    key = (variant, target["flavor"], target["platform"])
                    if key in found:
                        continue
                    phases = normalized_jobs(jobs, target)
                    if not phases:
                        # Queued whole runs have no jobs yet; retain their active
                        # status for scheduled targets instead of showing old green.
                        if run["status"] == "completed":
                            if run.get("event") not in {"schedule", "push"}:
                                continue  # A manual run may select another flavor.
                            conclusion = run.get("conclusion")
                            status = ("failed" if conclusion in {"failure", "timed_out", "startup_failure"}
                                      else "blocked" if conclusion == "cancelled" else "missing")
                        else:
                            status = "unknown"  # No flavor-dispatch identity until jobs exist.
                    else:
                        status, _reasons = attempt_status(phases)
                    found[key] = {
                        "identity": {"repository": REPOSITORY,
                                     "workflow": f".github/workflows/{workflow}",
                                     "runId": run["id"], "runAttempt": run["run_attempt"],
                                     "sourceRevision": run["head_sha"], "startedAt": run["run_started_at"]},
                        "status": status, "measuredAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "evidence": [{"url": f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}/attempts/{run['run_attempt']}"}],
                    }
        except CollectionError:
            available = False
        sources.append({"id": f"github-{variant}", "repository": REPOSITORY,
                        "status": "available" if available else "unavailable", "evidence": []})
        for row in rows:
            target = row["target"]
            if target["variant"] != variant:
                continue
            key = (variant, target["flavor"], target["platform"])
            evaluated = evaluate_row(row, found.get(key), None, None, None,
                                     collection_available=available, now=now,
                                     build_seconds=build_seconds,
                                     required_image_checks={"consumer-contract"},
                                     required_factory_checks={"package-supply"})
            if not available:
                evaluated["reasons"].append("github-collection-unavailable")
            row["health"] = evaluated
    return {"schemaVersion": 1, "kind": "build-health", "sourceRevision": source_revision,
            "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "coverageDigest": coverage["coverageDigest"],
            "collection": {"status": "available" if all(s["status"] == "available" for s in sources) else "degraded", "sources": sources},
            "freshnessPolicy": {"buildSeconds": build_seconds, "feedSeconds": feed_seconds},
            "targets": [r["health"] for r in rows]}


def markdown(document):
    lines = ["# Build health", "", f"Observed {document['generatedAt']}; collection {document['collection']['status']}.",
             "", "Successful jobs require authenticated package/image receipts before publication is verified.",
             "", "| Variant | Flavor | Platform | Status | Reasons |", "|---|---|---|---|---|"]
    for row in document["targets"]:
        target = row["target"]
        lines.append(f"| {target['variant']} | {target['flavor']} | {target['platform']} | {row['status']} | {', '.join(row['reasons'])} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(".github/build-config.yml"))
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--api-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    document = collect(config, args.source_revision, lambda endpoint: gh_fetch(endpoint, args.api_version))
    validate(document, expected_kind="build-health")
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text(markdown(document))


if __name__ == "__main__":
    main()
