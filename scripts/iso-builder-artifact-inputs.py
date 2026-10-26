#!/usr/bin/env python3
"""Bind a browser-built ISO from tuna-os/iso-builder to the strict harness inputs.

This serves iso-e2e.yml source `iso-builder-artifact`. Everything it produces is
labelled `diagnostic-unqualified`: the ISO came from a build that the browser
catalog gate refused to qualify, and nothing here can change that.

Two sub-commands, both fail-closed and offline:

  check-inputs   validate the dispatch inputs before any download starts
  derive         read the retained build-measurements file and the artifact
                 manifest, check them against the reassembled ISO, and write
                 the TUNAOS_QUAL_* environment plus a label file

Identities are taken only from what the producer run measured:

  media     sha256 of the reassembled ISO (must equal the expected hash, the
            manifest and the browser measurement)
  source    observedInputs.source.manifestDigest of the engine build result
  overlay   observedInputs.overlay.manifestDigest, status must be `applied`
  engine    sha256 of the WASM response the page instantiated
  browser   the Chromium product string of the measuring browser
  installer an operator-supplied digest, optional, labelled as such

The overlay and engine are never defaulted. A missing or malformed value stops
the run before any guest boots. The ISO hash is never reused as an identity.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NoReturn

LABEL = "diagnostic-unqualified"
LABEL_TEXT = "diagnostic, unqualified build"
PRODUCER_REPOSITORY = "tuna-os/iso-builder"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
RUN_ID = re.compile(r"^[1-9][0-9]{0,19}$")
ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
BROWSER = re.compile(r"^(HeadlessChrome|Chrome)/([1-9][0-9]*(?:\.[0-9]+)+)$")
MAX_JSON_BYTES = 1024 * 1024


def fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def digest(value, what: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        fail(f"{what} is missing or not sha256:<64 lowercase hex>")
    return value


def load_json(path: str, what: str) -> dict:
    p = Path(path)
    if not p.is_file() or p.stat().st_size > MAX_JSON_BYTES:
        fail(f"{what} is missing or larger than {MAX_JSON_BYTES} bytes: {path}")
    try:
        value = json.loads(p.read_text())
    except (json.JSONDecodeError, UnicodeError) as exc:
        fail(f"{what} is not valid JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{what} is not a JSON object")
    return value


def check_inputs(args: argparse.Namespace) -> None:
    if not RUN_ID.fullmatch(args.run_id or ""):
        fail("iso_builder_run_id must be a numeric run id")
    for name, value in (("iso_builder_artifact", args.artifact), ("iso_builder_evidence_artifact", args.evidence_artifact)):
        if not ARTIFACT_NAME.fullmatch(value or ""):
            fail(f"{name} is not a plain artifact name")
    if args.artifact == args.evidence_artifact:
        fail("the ISO artifact and the evidence artifact must be different artifacts")
    if not SHA40.fullmatch(args.producer_sha or ""):
        fail("iso_builder_sha must be a full 40-character lowercase commit SHA")
    digest(args.expected_sha256, "iso_expected_sha256")
    if args.installer_digest:
        digest(args.installer_digest, "qual_installer_digest")
    if not RUN_ID.fullmatch(args.attempt or ""):
        fail("iso_builder_attempt must be a numeric run attempt")
    print("iso-builder artifact inputs are well formed")
def verify_metadata(args: argparse.Namespace) -> None:
    run = load_json(args.run_metadata, "producer run metadata")
    artifacts = load_json(args.artifacts_metadata, "producer artifact metadata")
    if str(run.get("id")) != args.run_id:
        fail("GitHub run metadata id differs from the selected producer run")
    if (run.get("repository") or {}).get("full_name") != PRODUCER_REPOSITORY:
        fail("GitHub producer repository differs from " + PRODUCER_REPOSITORY)
    if (run.get("head_repository") or {}).get("full_name") != PRODUCER_REPOSITORY:
        fail("GitHub producer head repository differs from " + PRODUCER_REPOSITORY)
    if run.get("path") != ".github/workflows/ci.yml":
        fail("GitHub producer workflow is not .github/workflows/ci.yml")
    if run.get("head_sha") != args.producer_sha:
        fail("GitHub producer head SHA differs from the selected producer SHA")
    if run.get("status") != "completed":
        fail("GitHub producer run has not completed")
    run_repository = run.get("repository") or {}
    run_head_repository = run.get("head_repository") or {}
    if str(run.get("run_attempt")) != args.attempt:
        fail("GitHub producer attempt differs from the selected attempt")
    if run.get("conclusion") not in ("success", "failure"):
        fail(f"GitHub producer run concluded {run.get('conclusion')!r}")
    jobs = load_json(args.jobs_metadata, "producer attempt job metadata")
    jobs_list = jobs.get("jobs")
    if not isinstance(jobs_list, list):
        fail("GitHub producer attempt metadata has no jobs list")
    slug = f"{args.variant}-{args.flavor}"
    if any(not isinstance(other, dict) for other in jobs_list):
        fail("GitHub producer attempt metadata contains an invalid job")
    expected_prefix = f"full-matrix ({args.variant}:{args.flavor}, {slug}, "
    expected_chunk_name = f"iso-{slug}-run{args.run_id}-a{args.attempt}"
    expected_evidence_name = f"browser-evidence-{slug}-run{args.run_id}-a{args.attempt}"
    if args.artifact != expected_chunk_name or args.evidence_artifact != expected_evidence_name:
        fail("selected GitHub artifact names do not match the producer matrix target and attempt")
    expected_suffix = f", {args.platform}, true)"
    matches = [job for job in jobs_list if isinstance(job, dict)
               and isinstance(job.get("name"), str)
               and job["name"].startswith(expected_prefix) and job["name"].endswith(expected_suffix)]
    if len(matches) != 1:
        fail("GitHub producer attempt does not have exactly one matching full-matrix target job")
    job = matches[0]
    for other in jobs_list:
        if other is job:
            continue
        if other.get("status") != "completed":
            fail(f"GitHub producer job {other.get('name')!r} did not complete")
        if other.get("conclusion") not in ("success", "skipped"):
            fail(f"GitHub producer job {other.get('name')!r} concluded {other.get('conclusion')!r}")
    if job.get("status") != "completed" or job.get("conclusion") not in ("success", "failure"):
        fail("GitHub producer target job did not complete normally")
    steps = job.get("steps")
    if not isinstance(steps, list):
        fail("GitHub producer target job has no step metadata")
    steps_by_name = {step.get("name"): step for step in steps if isinstance(step, dict)}
    required = {
        f"build {args.variant}:{args.flavor} (": "success",
        "retain ISO as GitHub artifact (chunked, sha256-verified)": "success",
        "upload ISO chunks": "success",
        "download ISO artifact again": "success",
        "verify ISO artifact round trip": "success",
        "upload browser evidence (survives guest failure)": "success",
    }
    build_names = [name for name in steps_by_name if name.startswith(f"build {args.variant}:{args.flavor} (")]
    if len(build_names) != 1:
        fail("GitHub producer target job does not have exactly one matching ISO build step")
    for name, expected_conclusion in required.items():
        actual_name = build_names[0] if name.endswith(" (") else name
        step = steps_by_name.get(actual_name)
        if not step or step.get("status") != "completed" or step.get("conclusion") != expected_conclusion:
            fail(f"GitHub producer integrity step {actual_name!r} did not succeed")
    guest_name = f"verify guest under QEMU ({slug})"
    guest = steps_by_name.get(guest_name)
    if not guest or guest.get("status") != "completed" or guest.get("conclusion") not in ("success", "failure"):
        fail("GitHub producer guest verification did not complete normally")
    for step_name, step in steps_by_name.items():
        conclusion = step.get("conclusion")
        if step.get("status") != "completed":
            fail(f"GitHub producer step {step_name!r} did not complete")
        if conclusion in ("cancelled", "timed_out", "action_required", "stale"):
            fail(f"GitHub producer step {step_name!r} was {conclusion}")
        if conclusion == "failure" and step_name != guest_name:
            fail(f"GitHub producer step {step_name!r} failed outside guest verification")
    if (job.get("conclusion") == "success") != (guest.get("conclusion") == "success"):
        fail("GitHub producer job conclusion is not explained solely by guest verification")
    if run.get("conclusion") not in ("success", "failure"):
        fail(f"GitHub producer run concluded {run.get('conclusion')!r}")
    if (run.get("conclusion") == "success") != (job.get("conclusion") == "success"):
        fail("GitHub producer run conclusion is not explained solely by guest verification")
    values = artifacts.get("artifacts")
    if not isinstance(values, list):
        fail("GitHub artifact metadata has no artifact list")
    selected = []
    for name in (args.artifact, args.evidence_artifact):
        matches = [item for item in values if isinstance(item, dict) and item.get("name") == name]
        if len(matches) != 1:
            fail(f"expected exactly one GitHub artifact named {name!r}")
        artifact = matches[0]
        workflow_run = artifact.get("workflow_run") or {}
        if str(workflow_run.get("id")) != args.run_id:
            fail(f"artifact {name!r} belongs to a different GitHub run")
        if workflow_run.get("repository_id") != run_repository.get("id"):
            fail(f"artifact {name!r} belongs to a different repository")
        if workflow_run.get("head_repository_id") != run_head_repository.get("id"):
            fail(f"artifact {name!r} belongs to a different head repository")
        if workflow_run.get("head_sha") != args.producer_sha:
            fail(f"artifact {name!r} belongs to a different producer SHA")
        # GitHub's artifact workflow_run metadata omits run_attempt; the unique
        # attempt suffix in each artifact name binds it to the selected run.
        expected_suffix = f"-run{args.run_id}-a{args.attempt}"
        if not name.endswith(expected_suffix):
            fail(f"artifact {name!r} does not identify the selected run attempt")
        if artifact.get("expired") is not False or not isinstance(artifact.get("id"), int) or artifact["id"] < 1:
            fail(f"artifact {name!r} lacks a live GitHub artifact id")
        artifact_digest = digest(artifact.get("digest"), f"artifact {name!r} GitHub digest")
        selected.append({"id": artifact["id"], "name": name, "digest": artifact_digest})
    selected_json = json.dumps(selected, separators=(",", ":"))
    Path(args.out).write_text(json.dumps({
        "runId": args.run_id, "runAttempt": int(args.attempt), "headSha": args.producer_sha,
        "artifacts": selected,
    }, indent=2, sort_keys=True) + "\n")
    Path(args.output).write_text(f"artifacts={selected_json}\n")




def derive(args: argparse.Namespace) -> None:
    expected = digest(args.expected_sha256, "iso_expected_sha256")
    iso = Path(args.iso)
    if not iso.is_file():
        fail(f"reassembled ISO is missing: {iso}")
    iso_size = iso.stat().st_size

    measurements = load_json(args.measurements, "build measurements")
    manifest = load_json(args.manifest, "artifact manifest")

    if manifest.get("kind") != "candidate-iso-artifact-manifest" or manifest.get("schemaVersion") != 1:
        fail("artifact manifest is not candidate-iso-artifact-manifest v1")
    if manifest.get("qualification") != LABEL:
        fail(f"artifact manifest is labelled {manifest.get('qualification')!r}, not {LABEL!r}")
    producer = manifest.get("producer") or {}
    if producer.get("repository") != PRODUCER_REPOSITORY:
        fail("artifact manifest was not produced by " + PRODUCER_REPOSITORY)
    if producer.get("runId") != args.run_id or producer.get("sha") != args.producer_sha:
        fail("artifact manifest producer run or commit differs from the dispatch inputs")
    if (manifest.get("iso") or {}).get("sha256") != expected or (manifest.get("iso") or {}).get("sizeBytes") != iso_size:
        fail("artifact manifest ISO identity differs from the expected hash or the reassembled file")

    if measurements.get("kind") != "diagnostic-build-measurements" or measurements.get("schemaVersion") != 1:
        fail("measurements are not diagnostic-build-measurements v1")
    if measurements.get("qualification") != LABEL:
        fail(f"measurements are labelled {measurements.get('qualification')!r}, not {LABEL!r}")
    diag = measurements.get("diagnosticUnqualified")
    if not isinstance(diag, dict) or diag.get("label") != LABEL_TEXT:
        fail("measurements lack the diagnosticUnqualified label block")
    if diag.get("image") != f"tuna-os/{args.variant}:{args.flavor}":
        fail(f"measurements are for {diag.get('image')!r}, not tuna-os/{args.variant}:{args.flavor}")
    if diag.get("platform") != args.platform:
        fail(f"measurements are for platform {diag.get('platform')!r}, not {args.platform!r}")

    measured_iso = measurements.get("iso") or {}
    if measured_iso.get("sha256") != expected or measured_iso.get("sizeBytes") != iso_size:
        fail("browser measurement of the ISO differs from the expected hash or the reassembled file")

    build = measurements.get("engineBuildResult")
    if not isinstance(build, dict):
        fail("measurements carry no engineBuildResult; the overlay identity cannot be read (failing closed)")
    if build.get("bytesWritten") != iso_size:
        fail("engineBuildResult.bytesWritten differs from the ISO size")
    observed = build.get("observedInputs") or {}
    source = digest((observed.get("source") or {}).get("manifestDigest"), "observedInputs.source.manifestDigest")
    overlay_block = observed.get("overlay") or {}
    if overlay_block.get("status") != "applied":
        fail(f"observedInputs.overlay.status is {overlay_block.get('status')!r}, not 'applied'")
    overlay = digest(overlay_block.get("manifestDigest"), "observedInputs.overlay.manifestDigest")
    if overlay == expected:
        fail("the overlay digest equals the ISO hash; refusing a placeholder identity")
    engine = digest((measurements.get("loadedWasm") or {}).get("sha256"), "loadedWasm.sha256")
    if engine == expected:
        fail("the engine digest equals the ISO hash; refusing a placeholder identity")

    product = (measurements.get("browser") or {}).get("product")
    m = BROWSER.fullmatch(product or "")
    if not m:
        fail(f"browser product {product!r} is not a Chromium product string")
    browser_name, browser_version = m.group(1), m.group(2)

    installer_expectation = digest(args.installer_digest, "qual_installer_digest") if args.installer_digest else None

    env = {
        "TUNAOS_QUAL_MEDIA_DIGEST": expected,
        "TUNAOS_QUAL_SOURCE_DIGEST": source,
        "TUNAOS_QUAL_OVERLAY_DIGEST": overlay,
        "TUNAOS_QUAL_ENGINE_DIGEST": engine,
        "TUNAOS_QUAL_PLATFORM": args.platform,
        "TUNAOS_QUAL_BROWSER_NAME": browser_name,
        "TUNAOS_QUAL_BROWSER_VERSION": browser_version,
        "STRICT_PUBLISHED_MEDIA": "1",
        "TUNAOS_QUAL_DIAGNOSTIC": LABEL,
    }
    Path(args.out_env).write_text("".join(f"{k}={v}\n" for k, v in env.items()))

    label = {
        "schema": "IsoBuilderDiagnosticInputs/v1",
        "qualification": LABEL,
        "label": LABEL_TEXT,
        "notice": "Built in a browser from a target the catalog gate refuses to qualify. Nothing in this run qualifies the target.",
        "producer": {"repository": PRODUCER_REPOSITORY, "runId": args.run_id, "runAttempt": producer.get("runAttempt"), "sha": args.producer_sha},
        "iso": {"sha256": expected, "sizeBytes": iso_size},
        "target": {"image": diag["image"], "platform": args.platform, "gateReason": diag.get("gateReason")},
        "identities": {
            "media": {"value": expected, "origin": "sha256 of the reassembled ISO; equals the manifest and the browser measurement"},
            "source": {"value": source, "origin": "engineBuildResult.observedInputs.source.manifestDigest"},
            "overlay": {
                "value": overlay,
                "origin": "engineBuildResult.observedInputs.overlay.manifestDigest",
                "baseAnnotationMatched": overlay_block.get("baseAnnotationMatched"),
            },
            "engine": {"value": engine, "origin": "sha256 of the WASM response the page instantiated"},
            "installer": {"value": None, "origin": "not established from a media-bound frontend receipt; evidence emission will fail closed"},
            "installerExpectation": (
                {"value": installer_expectation, "origin": "operator supplied; expectation only, not measured identity"}
                if installer_expectation
                else {"value": None, "origin": "not supplied"}
            ),
            "browser": {"name": browser_name, "version": browser_version, "origin": "Browser.getVersion of the measuring Chromium"},
        },
        "browserResourceProfile": "memory and free disk fall back to the QEMU runner's own values; they are not the browser's",
    }
    Path(args.out_label).write_text(json.dumps(label, indent=2, sort_keys=True) + "\n")
    print(f"derived {len(env)} values for {LABEL} media {expected[:19]}...")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("verify-metadata")
    p.add_argument("--run-id", required=True)
    p.add_argument("--attempt", required=True)
    p.add_argument("--artifact", required=True)
    p.add_argument("--evidence-artifact", required=True)
    p.add_argument("--producer-sha", required=True)
    p.add_argument("--run-metadata", required=True)
    p.add_argument("--artifacts-metadata", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--jobs-metadata", required=True)
    p.add_argument("--variant", required=True)
    p.add_argument("--flavor", required=True)
    p.add_argument("--platform", required=True)
    p.set_defaults(fn=verify_metadata)

    for name in ("check-inputs", "derive"):
        p = sub.add_parser(name)
        if name == "check-inputs":
            p.add_argument("--attempt", required=True)
        p.add_argument("--run-id", required=True)
        p.add_argument("--artifact", required=True)
        p.add_argument("--evidence-artifact", required=True)
        p.add_argument("--producer-sha", required=True)
        p.add_argument("--expected-sha256", required=True)
        p.add_argument("--installer-digest", default="")
        if name == "derive":
            p.add_argument("--iso", required=True)
            p.add_argument("--measurements", required=True)
            p.add_argument("--manifest", required=True)
            p.add_argument("--variant", required=True)
            p.add_argument("--flavor", required=True)
            p.add_argument("--platform", required=True)
            p.add_argument("--out-env", required=True)
            p.add_argument("--out-label", required=True)
            p.set_defaults(fn=derive)
        else:
            p.set_defaults(fn=check_inputs)
    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
