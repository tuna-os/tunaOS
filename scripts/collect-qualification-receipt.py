#!/usr/bin/env python3
"""Collect one authenticated browser ISO qualification receipt (#3381).

Usage: collect-qualification-receipt.py <iso-builder-run-id> <slug>

Downloads `qualification-receipt-<slug>-run<id>-a<attempt>` from a successful
tuna-os/iso-builder ci.yml run on main, authenticates receipt.json against its
build-provenance bundle with `gh attestation verify`, validates it against
BrowserIsoQualificationReceipt/v1 (scripts/lib/qualification_receipt.py), and
writes its exact bytes to iso-qualification/receipts/<sha256 hex>.json.

stdout is the `cutover_targets` entry to add to tunaos.toml [iso_delivery]: the
linux/amd64 target. arm64 gets none: an amd64 receipt proves no arm64 install.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import qualification_receipt, tunaos_config
from lib.gh import GhError, gh

REPOSITORY = qualification_receipt.PRODUCER["repository"]
WORKFLOW = qualification_receipt.PRODUCER["workflow"]
SOURCE_REF = qualification_receipt.PRODUCER["ref"]
SIGNER_WORKFLOW = f"{REPOSITORY}/{WORKFLOW}"
EVENTS = {"workflow_dispatch", "schedule"}


class CollectError(RuntimeError):
    """The run, its attestation, or its receipt does not qualify a target."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectError(message)


def verify_run(run_id: int) -> dict[str, Any]:
    run = json.loads(gh(["api", f"repos/{REPOSITORY}/actions/runs/{run_id}"], retries=3))
    require(run.get("id") == run_id, f"run {run_id}: API returned run {run.get('id')}")
    for field, expected in (
        (("repository", "full_name"), REPOSITORY),
        (("head_repository", "full_name"), REPOSITORY),
        (("path",), WORKFLOW),
        (("head_branch",), "main"),
        (("status",), "completed"),
        (("conclusion",), "success"),
    ):
        value: Any = run
        for key in field:
            value = value.get(key) if isinstance(value, dict) else None
        require(value == expected, f"run {run_id}: {'.'.join(field)} is {value!r}, expected {expected!r}")
    require(run.get("event") in EVENTS,
            f"run {run_id}: event {run.get('event')!r} is not one of {sorted(EVENTS)}")
    require(isinstance(run.get("head_sha"), str)
            and bool(qualification_receipt.COMMIT.fullmatch(run["head_sha"])),
            f"run {run_id}: head_sha is not a commit")
    return run


def list_artifacts(run_id: int) -> list[dict[str, Any]]:
    output = gh(["api", "--paginate", f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100",
                 "--jq", ".artifacts[]"], retries=3)
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def receipt_artifact(artifacts: list[dict[str, Any]], run_id: int, slug: str) -> tuple[str, int]:
    """The newest unexpired receipt artifact for `slug` and its run attempt."""
    pattern = re.compile(rf"qualification-receipt-{re.escape(slug)}-run{run_id}-a([1-9][0-9]*)")
    found = {
        int(match.group(1)): artifact["name"]
        for artifact in artifacts
        if (match := pattern.fullmatch(str(artifact.get("name", "")))) and artifact.get("expired") is False
    }
    require(bool(found), f"run {run_id} has no unexpired qualification-receipt-{slug}-run{run_id}-a<N> artifact")
    attempt = max(found)
    return found[attempt], attempt


def verify_attestation(receipt: Path, bundle: Path, run: dict[str, Any], attempt: int) -> None:
    output = gh([
        "attestation", "verify", str(receipt),
        "--repo", REPOSITORY,
        "--signer-workflow", SIGNER_WORKFLOW,
        "--source-ref", SOURCE_REF,
        "--source-digest", run["head_sha"],
        "--bundle", str(bundle),
        "--format", "json",
    ])
    results = json.loads(output)
    require(isinstance(results, list) and bool(results), "gh attestation verify returned no verified attestation")
    invocation = f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}/attempts/{attempt}"
    for result in results:
        certificate = result.get("verificationResult", {}).get("signature", {}).get("certificate", {})
        require(certificate.get("runInvocationURI") == invocation,
                f"attestation was signed by {certificate.get('runInvocationURI')!r}, not {invocation}")


def check_binding(receipt: dict[str, Any], run: dict[str, Any], attempt: int, slug: str,
                  artifacts: list[dict[str, Any]]) -> None:
    producer = receipt["producer"]
    require(producer["runId"] == run["id"] and producer["runAttempt"] == attempt,
            f"receipt names run {producer['runId']} attempt {producer['runAttempt']}")
    require(producer["sha"] == run["head_sha"], f"receipt producer.sha differs from run head {run['head_sha']}")
    iso_name = f"iso-{slug}-run{run['id']}-a{attempt}"
    require(producer["isoArtifactName"] == iso_name, f"receipt names ISO artifact {producer['isoArtifactName']!r}")
    require(any(artifact.get("id") == producer["isoArtifactId"] and artifact.get("name") == iso_name
                for artifact in artifacts),
            f"run {run['id']} has no artifact {iso_name} with id {producer['isoArtifactId']}")


def require_amd64_build(receipt: dict[str, Any]) -> None:
    """The receipt's flavor must be built for linux/amd64, the platform it proves.
    An amd64 receipt proves no arm64 install or boot, so it never names arm64."""
    variant_id, flavor_id = receipt["target"]["variant"], receipt["target"]["flavor"]
    config = tunaos_config.matrix(tunaos_config.load())
    variant = next((v for v in config["variants"] if v["id"] == variant_id), None)
    require(variant is not None, f"tunaos.toml has no variant {variant_id!r}")
    flavor = next((f for f in variant.get("flavors", []) if f["id"] == flavor_id), None)
    require(flavor is not None and flavor.get("build_image") is True,
            f"tunaos.toml does not build {variant_id}:{flavor_id}")
    platforms = flavor.get("platforms", variant.get("platforms", []))
    require(qualification_receipt.BASIS_PLATFORM in platforms,
            f"tunaos.toml does not build {variant_id}:{flavor_id} for linux/amd64")


def toml_entry(receipt: dict[str, Any], platform: str, evidence: str) -> str:
    fields = {
        "variant": receipt["target"]["variant"],
        "flavor": receipt["target"]["flavor"],
        "platform": platform,
        "qualification": receipt["qualification"],
        "qualified_at": receipt["qualifiedAt"][:10],
        "evidence": evidence,
    }
    return "  { " + ", ".join(f"{key} = {json.dumps(value)}" for key, value in fields.items()) + " },"


def collect(run_id: int, slug: str, receipts_dir: Path) -> tuple[dict[str, Any], str]:
    run = verify_run(run_id)
    artifacts = list_artifacts(run_id)
    name, attempt = receipt_artifact(artifacts, run_id, slug)
    with tempfile.TemporaryDirectory() as tmp:
        download = Path(tmp)
        gh(["run", "download", str(run_id), "--repo", REPOSITORY, "--name", name, "--dir", str(download)], retries=3)
        receipt_path, bundle_path = download / "receipt.json", download / "bundle.jsonl"
        require(receipt_path.is_file() and bundle_path.is_file(), f"{name} lacks receipt.json or bundle.jsonl")
        verify_attestation(receipt_path, bundle_path, run, attempt)
        data = receipt_path.read_bytes()
    try:
        receipt = qualification_receipt.parse(data)
    except qualification_receipt.ReceiptError as exc:
        raise CollectError(f"{name}: {exc}") from exc
    check_binding(receipt, run, attempt, slug, artifacts)
    require_amd64_build(receipt)
    evidence = qualification_receipt.digest(data)
    destination = qualification_receipt.path_for(evidence, receipts_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print(f"wrote {destination}", file=sys.stderr)
    return receipt, evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_id", type=int, help="tuna-os/iso-builder ci.yml run ID")
    parser.add_argument("slug", help="edition slug, as in iso-<slug>-run<id>-a<attempt>")
    parser.add_argument("--receipts-dir", type=Path, default=qualification_receipt.RECEIPTS_DIR,
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        receipt, evidence = collect(args.run_id, args.slug, args.receipts_dir)
    except (CollectError, GhError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    base = f"{receipt['target']['variant']}-{receipt['target']['flavor']}"
    print("# Add to cutover_targets in tunaos.toml [iso_delivery]:")
    print(toml_entry(receipt, qualification_receipt.BASIS_PLATFORM, evidence))
    print(f"# Also list in retained_r2_isos every published {base}-latest*.iso and versioned {base}-*.iso in R2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
