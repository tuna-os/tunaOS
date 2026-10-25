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
    print("iso-builder artifact inputs are well formed")


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

    installer = digest(args.installer_digest, "qual_installer_digest") if args.installer_digest else None

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
    if installer:
        env["TUNAOS_QUAL_INSTALLER_DIGEST"] = installer
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
            "installer": (
                {"value": installer, "origin": "operator supplied; not a frontend identity, not read from the media"}
                if installer
                else {"value": None, "origin": "not supplied; evidence emission will fail closed"}
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
    for name in ("check-inputs", "derive"):
        p = sub.add_parser(name)
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
