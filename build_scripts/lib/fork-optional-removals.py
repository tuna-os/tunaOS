#!/usr/bin/env python3
"""Reviewed opt-in stock removals at the existing late desktop boundary.

Only the committed policy is accepted. The root redirects evidence files, NOT
native package commands or the desktop checker. Production runs inside the build
container at /. Tests must redirect every native command and contract execution.
No automatic repair or retry is safe after a failure; discard the build root.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
POLICY = HERE / "fork-optional-removals.json"
CHECKER = HERE.parent / "checks/verify-desktop-experience.sh"
SPEC = importlib.util.spec_from_file_location("fork_removal_inventory", HERE / "fork-removal-inventory.py")
INVENTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVENTORY)
ProtectionError = INVENTORY.ProtectionError
SHA = INVENTORY.SHA


def read_json(path):
    path = INVENTORY.checked_path(path)
    with path.open("rb") as stream:
        data = stream.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ProtectionError("JSON evidence is too large")
    return json.loads(data, object_pairs_hook=INVENTORY.unique_pairs), hashlib.sha256(data).hexdigest()


def policy():
    value, digest = read_json(POLICY)
    if not isinstance(value, dict) or set(value) != {
            "schema_version", "policy_id", "routes", "flavors", "desktop_contract", "target_removal_scripts"}:
        raise ProtectionError("invalid optional-removal policy schema")
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["policy_id"] != "reviewed-optional-stock-v1" or value["flavors"] != ["gnome"]
            or value["desktop_contract"] != "strict-before-and-after"
            or value["target_removal_scripts"] != "reject"):
        raise ProtectionError("unsupported optional-removal policy")
    if not isinstance(value["routes"], list) or len(value["routes"]) != 2:
        raise ProtectionError("invalid optional-removal policy routes")
    routes = set()
    for route in value["routes"]:
        if (not isinstance(route, dict) or set(route) != {"variant", "package_manager", "packages"}
                or route["packages"] != ["fastfetch"]
                or not isinstance(route["variant"], str) or not isinstance(route["package_manager"], str)):
            raise ProtectionError("invalid optional-removal policy route")
        routes.add((route["variant"], route["package_manager"]))
    if routes != {("grouper", "apt"), ("yellowfin", "dnf")}:
        raise ProtectionError("unsupported optional-removal policy route")
    return value, digest


def validate_intent(packages, manager, variant, flavor):
    """Compiler-facing validation; no package queries and no policy override."""
    value, digest = policy()
    if not isinstance(packages, dict) or set(packages) != {"add", "optional", "remove", "repositories"}:
        raise ProtectionError("invalid package intent fields")
    names = []
    for key in ("add", "optional", "remove"):
        if not isinstance(packages[key], list) or any(not isinstance(name, str) for name in packages[key]):
            raise ProtectionError("package names must be lists of strings")
        names.extend(packages[key])
    if len(names) != len(set(names)):
        raise ProtectionError("duplicate or contradictory package intent")
    if not isinstance(packages["repositories"], list):
        raise ProtectionError("repositories must be a list")
    if packages["remove"]:
        if (variant, manager) not in {(r["variant"], r["package_manager"]) for r in value["routes"]} or flavor not in value["flavors"]:
            raise ProtectionError("optional stock removals are supported only for grouper/apt and yellowfin/dnf GNOME")
        if packages["remove"] != ["fastfetch"]:
            raise ProtectionError("only the exact reviewed optional stock package fastfetch may be removed")
    return {"policy_id": value["policy_id"], "policy_sha256": digest}


def validate(manifest):
    """Validate generated manifest identity and the separate removal policy."""
    value, _ = read_json(manifest)
    if not isinstance(value, dict) or set(value) != {
            "schema_version", "variant", "flavor", "platform", "package_manager", "image", "intent", "sources", "assets"}:
        raise ProtectionError("invalid generated fork manifest fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ProtectionError("invalid generated fork manifest schema")
    for key in ("variant", "flavor", "package_manager"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value[key]):
            raise ProtectionError("invalid fork route identity")
    if not isinstance(value["platform"], str) or value["platform"] not in {"linux/amd64", "linux/amd64/v2", "linux/arm64"}:
        raise ProtectionError("unsupported fork platform")
    if (not isinstance(value["sources"], dict) or set(value["sources"]) != {"sha256"}
            or not isinstance(value["sources"]["sha256"], str) or not SHA.fullmatch(value["sources"]["sha256"])):
        raise ProtectionError("invalid fork source identity")
    if (not isinstance(value["intent"], dict) or set(value["intent"]) != {"branding", "packages"}
            or not isinstance(value["intent"]["branding"], dict)
            or not isinstance(value["assets"], dict) or not isinstance(value["image"], dict)):
        raise ProtectionError("invalid fork intent")
    approved = validate_intent(value["intent"]["packages"], value["package_manager"], value["variant"], value["flavor"])
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    identity = {"package_manager": value["package_manager"], "source_sha256": value["sources"]["sha256"],
                "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
                "variant": value["variant"], "flavor": value["flavor"], "platform": value["platform"], **approved}
    return value, identity


def checked_root(root):
    root = Path(root)
    if not root.is_absolute() or not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ProtectionError("evidence root must be an existing absolute directory without symlinks")
    return root


def runtime_route(value, root):
    """Match native family, Tuna variant and architecture before any mutation."""
    release = INVENTORY.checked_path(root / "usr/lib/os-release")
    fields = {}
    for line in release.read_text().splitlines():
        if line.startswith("ID=") or line.startswith("VARIANT_ID="):
            key, _, item = line.partition("=")
            if key in fields:
                raise ProtectionError("ambiguous native OS identity")
            # Read data, never source this file as shell code. Both quoted and
            # unquoted tokens are emitted by supported stock os-release files.
            if len(item) >= 2 and item[0] in {"\"", "'"} and item[-1] == item[0]:
                item = item[1:-1]
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", item):
                raise ProtectionError("invalid native OS identity")
            fields[key] = item
    expected_id = {"grouper": "ubuntu", "yellowfin": "almalinux"}.get(value["variant"])
    if fields != {"ID": expected_id, "VARIANT_ID": value["variant"]}:
        raise ProtectionError("native OS family/variant differs from reviewed fork route")
    machine = os.uname().machine
    if (value["platform"], machine) not in {
            ("linux/amd64", "x86_64"), ("linux/amd64/v2", "x86_64"), ("linux/arm64", "aarch64")}:
        raise ProtectionError("native architecture differs from reviewed fork platform")


def command(args):
    result = subprocess.run(args, check=True, text=True, capture_output=True,
                            env={**os.environ, "LC_ALL": "C"}, timeout=300)
    return result.stdout, result.stderr


def health(manager):
    """Fail before removal on incomplete native state or broken dependencies."""
    if manager == "apt":
        output, errors = command(["dpkg", "--audit"])
        if output.strip() or errors.strip():
            raise ProtectionError("dpkg audit is not clean")
        command(["apt-get", "check"])
    elif manager == "dnf":
        output, errors = command(["rpm", "--verifydb"])
        if output.strip() or errors.strip():
            raise ProtectionError("RPM database verification is not clean")
        command(["dnf", "-q", "check"])
    else:
        raise ProtectionError("unsupported removal health backend")


def reject_target_scripts(manager):
    """No target removal scripts have been qualified by the initial policy."""
    if manager == "apt":
        output, errors = command(["dpkg-query", "--control-list", "fastfetch"])
        files = output.splitlines()
        if errors.strip() or not files or any(not re.fullmatch(r"[a-zA-Z0-9_.-]+", name) for name in files):
            raise ProtectionError("unrecognized fastfetch dpkg control-file inventory")
        if {"prerm", "postrm", "triggers"} & set(files):
            raise ProtectionError("fastfetch target removal scripts are not qualified")
    else:
        # --scripts also rejects install-only scripts conservatively. Package
        # and file triggers are separate RPM query modes and must be checked.
        for query in ("--scripts", "--triggers", "--filetriggers"):
            output, errors = command(["rpm", "-q", query, "--", "fastfetch"])
            if output.strip() or errors.strip():
                raise ProtectionError("fastfetch target scripts/triggers are not qualified")


def strict_contract(context, root, desktop):
    """Execute the committed checker and require its freshly written clean result."""
    if desktop != "gnome":
        raise ProtectionError("only the GNOME desktop contract is qualified for optional removals")
    checker = INVENTORY.checked_path(Path(context) / "build_scripts/checks/verify-desktop-experience.sh")
    expected = INVENTORY.checked_path(CHECKER)
    checker_hash = hashlib.sha256(checker.read_bytes()).hexdigest()
    if checker_hash != hashlib.sha256(expected.read_bytes()).hexdigest():
        raise ProtectionError("desktop checker differs from the committed implementation")
    marker = root / "usr/share/tunaos/experience-contracts" / desktop
    if any(p.is_symlink() for p in (marker, *marker.parents)):
        raise ProtectionError("desktop contract marker path cannot contain symlinks")
    if marker.exists():
        INVENTORY.checked_path(marker)
        marker.unlink()
    # A prior pass is not evidence. Exit zero without a new strict marker also
    # fails. The actual checker, not a user-specified callback, runs each time.
    output, errors = command(["bash", str(checker), desktop])
    marker = INVENTORY.checked_path(marker)
    data = marker.read_bytes()
    fields = {}
    for line in data.decode().splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in fields:
            raise ProtectionError("invalid fresh desktop contract marker")
        fields[key] = value
    if (set(fields) != {"desktop", "experience", "validated_at_build"}
            or fields["desktop"] != desktop or fields["validated_at_build"] != "true"
            or fields["experience"] != "projectbluefin/bluefin-lts"
            or f"desktop experience contract passed: {desktop} ({fields['experience']})" not in output.splitlines()
            or "TUNAOS_DESKTOP_CONTRACT_WAIVED" in output + errors
            or "TUNAOS_DESKTOP_CONTRACT_FAIL" in output + errors):
        raise ProtectionError("desktop contract did not freshly pass without waivers")
    return {"desktop": desktop, "status": "passed", "checker_sha256": checker_hash,
            "marker_sha256": hashlib.sha256(data).hexdigest()}


def capture(manifest, baseline, root):
    root = checked_root(root)
    value, identity = validate(manifest)
    if not value["intent"]["packages"]["remove"]:
        raise ProtectionError("no optional stock removal requested")
    INVENTORY.checked_path(baseline, output=True)
    runtime_route(value, root)
    health(identity["package_manager"])
    records = INVENTORY.snapshot(identity["package_manager"])
    if not records or "fastfetch" not in {r["name"] for r in records}:
        raise ProtectionError("requested optional stock target is not installed in the untouched desktop")
    INVENTORY.write_new(baseline, {"schema_version": 1, "stage": "stock-desktop", **identity, "packages": records})
    return hashlib.sha256(Path(baseline).read_bytes()).hexdigest()


def apply(manifest, baseline, baseline_sha256, receipt, context, root, desktop):
    root = checked_root(root)
    value, identity = validate(manifest)
    if value["intent"]["packages"]["remove"] != ["fastfetch"] or desktop != identity["flavor"]:
        raise ProtectionError("explicit reviewed GNOME removal intent required")
    if not isinstance(baseline_sha256, str) or not SHA.fullmatch(baseline_sha256):
        raise ProtectionError("trusted baseline digest is required")
    INVENTORY.checked_path(receipt, output=True)
    runtime_route(value, root)
    records, digest = INVENTORY.read_baseline(baseline, "stock-desktop", identity)
    if digest != baseline_sha256:
        raise ProtectionError("stock baseline differs from the digest captured before fork additions")
    if "fastfetch" not in {r["name"] for r in records}:
        raise ProtectionError("requested target is not an optional stock package in this baseline")
    before = INVENTORY.snapshot(identity["package_manager"])
    baseline_pairs = {(r["name"], r["architecture"]) for r in records}
    current_pairs = {(r["name"], r["architecture"]) for r in before}
    if not baseline_pairs <= current_pairs:
        raise ProtectionError("stock name/architecture disappeared during fork additions")
    if "fastfetch" not in {r["name"] for r in before}:
        raise ProtectionError("requested removal target is no longer installed")
    health(identity["package_manager"])
    reject_target_scripts(identity["package_manager"])
    precontract = strict_contract(context, root, desktop)
    # Nothing may change the native inventory between protection and mutation,
    # including the pre-contract command. A single caller owns the build root.
    if INVENTORY.snapshot(identity["package_manager"]) != before:
        raise ProtectionError("native inventory changed during the pre-removal desktop contract")
    command(["bash", "-c", 'source "$1"; shift; _tunaos_remove_exact_native "$@"',
             "reviewed-optional-removal", str(HERE / "fork-removals.sh"), identity["package_manager"], "fastfetch"])
    after = INVENTORY.snapshot(identity["package_manager"])
    expected = [r for r in before if r["name"] != "fastfetch"]
    if after != expected:
        raise ProtectionError("unexpected package delta; discard the failed build root")
    health(identity["package_manager"])
    postcontract = strict_contract(context, root, desktop)
    if INVENTORY.snapshot(identity["package_manager"]) != expected:
        raise ProtectionError("native inventory changed during the post-removal desktop contract")
    # Recheck mutable evidence before reporting success. The shell caller must
    # retain baseline_sha256 in its own state, never reread it from the image.
    _, final_identity = validate(manifest)
    _, final_hash = INVENTORY.read_baseline(baseline, "stock-desktop", identity)
    if final_identity != identity or final_hash != baseline_sha256:
        raise ProtectionError("manifest, policy or baseline changed during optional removal")
    result = {"schema_version": 1, "status": "complete", **identity,
              "stock_baseline_sha256": baseline_sha256, "removed": ["fastfetch"],
              "before": before, "after": after, "contracts": {"before": precontract, "after": postcontract}}
    INVENTORY.write_new(receipt, result)
    return result


def verify_complete(manifest, baseline, receipt, context, root, desktop):
    """Recheck a completed earlier boundary; never authorize another removal."""
    root = checked_root(root)
    value, identity = validate(manifest)
    if value["intent"]["packages"]["remove"] != ["fastfetch"] or desktop != identity["flavor"]:
        raise ProtectionError("explicit reviewed GNOME removal intent required")
    runtime_route(value, root)
    result, receipt_hash = read_json(receipt)
    keys = {"schema_version", "status", "stock_baseline_sha256", "removed", "before", "after", "contracts", *identity}
    if (not isinstance(result, dict) or set(result) != keys
            or type(result["schema_version"]) is not int or result["schema_version"] != 1
            or result["status"] != "complete" or result["removed"] != ["fastfetch"]
            or any(result[k] != v for k, v in identity.items())):
        raise ProtectionError("invalid completed removal receipt or provenance")
    before = INVENTORY.validate_records(result["before"], identity["package_manager"])
    after = INVENTORY.validate_records(result["after"], identity["package_manager"])
    if ("fastfetch" not in {r["name"] for r in before}
            or after != [r for r in before if r["name"] != "fastfetch"]):
        raise ProtectionError("completed receipt does not contain the exact reviewed removal delta")
    records, baseline_hash = INVENTORY.read_baseline(baseline, "stock-desktop", identity)
    if baseline_hash != result["stock_baseline_sha256"]:
        raise ProtectionError("completed receipt baseline hash mismatch")
    if ("fastfetch" not in {r["name"] for r in records}
            or not {(r["name"], r["architecture"]) for r in records}
            <= {(r["name"], r["architecture"]) for r in before}):
        raise ProtectionError("completed receipt does not protect the stock baseline")
    contracts = result["contracts"]
    if not isinstance(contracts, dict) or set(contracts) != {"before", "after"}:
        raise ProtectionError("invalid completed desktop contract evidence")
    checker_hash = hashlib.sha256(INVENTORY.checked_path(CHECKER).read_bytes()).hexdigest()
    for evidence in contracts.values():
        if (not isinstance(evidence, dict) or set(evidence) != {"desktop", "status", "checker_sha256", "marker_sha256"}
                or evidence["desktop"] != desktop or evidence["status"] != "passed"
                or evidence["checker_sha256"] != checker_hash
                or not isinstance(evidence["marker_sha256"], str) or not SHA.fullmatch(evidence["marker_sha256"])):
            raise ProtectionError("invalid completed desktop contract evidence")
    if INVENTORY.snapshot(identity["package_manager"]) != after:
        raise ProtectionError("native inventory differs from the completed removal receipt")
    health(identity["package_manager"])
    fresh = strict_contract(context, root, desktop)
    if fresh != contracts["after"]:
        raise ProtectionError("fresh desktop contract differs from completed removal evidence")
    if INVENTORY.snapshot(identity["package_manager"]) != after:
        raise ProtectionError("native inventory changed during completed receipt verification")
    _, final_identity = validate(manifest)
    _, final_baseline_hash = INVENTORY.read_baseline(baseline, "stock-desktop", identity)
    _, final_receipt_hash = read_json(receipt)
    if final_identity != identity or final_baseline_hash != baseline_hash or final_receipt_hash != receipt_hash:
        raise ProtectionError("completed removal evidence changed during verification")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "capture", "apply", "verify-complete"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--manifest", type=Path, required=True)
        if name != "validate":
            cmd.add_argument("--baseline", type=Path, required=True)
            cmd.add_argument("--root", type=Path, required=True)
        if name == "apply":
            cmd.add_argument("--baseline-sha256", required=True)
        if name in {"apply", "verify-complete"}:
            cmd.add_argument("--receipt", type=Path, required=True)
            cmd.add_argument("--context", type=Path, required=True)
            cmd.add_argument("--desktop", required=True)
    args = vars(parser.parse_args())
    action = args.pop("command")
    try:
        if action == "capture":
            print(capture(**args))
        elif action == "validate":
            validate(**args)
        elif action == "verify-complete":
            verify_complete(**args)
        else:
            apply(**args)
    except (ProtectionError, OSError, UnicodeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"fork optional removals: {exc}; discard a failed build root, do not repair/retry", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr or exc.stdout
            if detail:
                print(detail, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
