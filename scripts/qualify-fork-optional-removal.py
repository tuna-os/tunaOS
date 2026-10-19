#!/usr/bin/env python3
"""Prove optional removal in a disposable child of a locally built GNOME image.

This does not qualify image identity, boot, installation, or the original image.
The source image is addressed by immutable local ID and is never tagged or pushed.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_fork", ROOT / "scripts/prepare-fork-config.py")
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)

CHILD = r'''
set -euo pipefail
source /run/context/build_scripts/lib.sh
source /run/context/build_scripts/lib/fork-packages.sh
manifest=/run/context/manifests/fork-config.json
ancestor=/proof/ancestor-manifest.json
variant=$(jq -r .variant "$manifest")
flavor=$(jq -r .flavor "$manifest")
platform=$(jq -r .platform "$manifest")
receipt="/usr/share/tunaos/fork-config/packages/${variant}--${flavor}--${platform//\//-}.json"
[[ -f "$receipt" && ! -L "$receipt" ]]
canonical=$(jq -cS . "$ancestor")
digest=$(printf '%s' "$canonical" | sha256sum)
digest=${digest%% *}
jq -e --arg digest "$digest" --arg variant "$variant" --arg flavor "$flavor" --arg platform "$platform" \
  '.status == "complete" and .manifest_sha256 == $digest and .variant == $variant and .flavor == $flavor and .platform == $platform' "$receipt" >/dev/null
# This exact file belongs to the disposable child only. Preserve it as ancestry
# evidence before the real consumer writes its distinct proof receipt.
[[ ! -e /evidence/ancestor-package-receipt.json ]]
mv "$receipt" /evidence/ancestor-package-receipt.json
tunaos_apply_fork_packages /run/context /
jq -e '.status == "pending-removal"' "$receipt" >/dev/null
tunaos_finalize_fork_packages /run/context gnome /
jq -e '.status == "complete" and .remove == ["fastfetch"]' "$receipt" >/dev/null
cp "$receipt" /evidence/package-receipt.json
cp "${receipt}.baseline.json" /evidence/stock-baseline.json
cp "${receipt}.removal.json" /evidence/native-removal-receipt.json
'''


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def qualify(image, variant, ancestor_manifest, output, root=ROOT):
    if variant not in {"grouper", "yellowfin"}:
        raise ValueError("only grouper and yellowfin have an optional-removal policy")
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("proof output ancestors must not be symlinks")
    if output.exists() or output.is_symlink():
        raise ValueError("proof output must be a new directory")
    if not ancestor_manifest.is_file() or ancestor_manifest.is_symlink():
        raise ValueError("ancestor manifest must be a regular file")
    ancestor = json.loads(ancestor_manifest.read_text(), object_pairs_hook=unique_pairs)
    if ancestor.get("variant") != variant or ancestor.get("flavor") != "gnome":
        raise ValueError("ancestor must be the matching GNOME source manifest")
    platform = ancestor.get("platform")
    if platform not in {"linux/amd64", "linux/amd64/v2", "linux/arm64"}:
        raise ValueError("unsupported ancestor platform")
    inspected = json.loads(subprocess.check_output(["podman", "image", "inspect", image], text=True), object_pairs_hook=unique_pairs)
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise ValueError("image inspection must identify exactly one local image")
    image_id = inspected[0].get("Id", "")
    if re.fullmatch(r"[0-9a-f]{64}", image_id):
        image_id = "sha256:" + image_id
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("source image must have an immutable local image ID")
    output.mkdir(parents=True)
    config = {"schema_version": 1, "catalog": {"sha256": PREPARE.COMPILER.source_receipt(root)["sha256"]},
              "image": {"registry": "localhost", "namespace": "package-removal-proof"},
              "targets": {"variants": [variant], "flavors": ["gnome"], "platforms": [platform]},
              "global": {"packages": {"remove": ["fastfetch"]}}}
    config_path = output / "package-only.yaml"
    config_path.write_text(yaml.safe_dump(config))
    prepared = output / "contexts"
    builds = PREPARE.prepare(config_path, prepared, root)
    if len(builds) != 1:
        raise ValueError("proof must produce exactly one context")
    context = prepared / builds[0]["context"]
    if (context / "manifests/fork-identity.json").exists():
        raise ValueError("package-only proof must not carry an old paired identity authority")
    manifest = json.loads((context / "manifests/fork-config.json").read_text())
    if manifest.get("sources") != config["catalog"]:
        raise ValueError("proof manifest source pin differs from the compiler source receipt")
    evidence = output / "evidence"
    evidence.mkdir()
    # Store a copy, so the mounted ancestry input cannot change concurrently.
    ancestry = output / "ancestor-manifest.json"
    ancestry.write_text(json.dumps(ancestor, indent=2) + "\n")
    result = {"schema_version": 1, "scope": "disposable-package-contract-only", "status": "running",
              "source_image_id": image_id, "ancestor_manifest_sha256": canonical_digest(ancestor),
              "proof_manifest_sha256": canonical_digest(manifest), "variant": variant, "platform": platform,
              "identity_qualification": "not-run", "boot_qualification": "not-run", "installation": "not-run"}
    receipt = output / "proof.json"
    receipt.write_text(json.dumps(result, indent=2) + "\n")
    container_name = "tuna-fork-removal-" + uuid.uuid4().hex
    result["container_name"] = container_name
    command = ["podman", "run", "--pull=never", "--name", container_name,
               "--label", f"org.tunaos.package-proof={container_name}", "--network=none", "--entrypoint", "/bin/bash",
               "--env", f"IMAGE_NAME_VARIANT={variant}", "--env", f"IMAGE_NAME={variant}",
               "--env", "TUNAOS_IMAGE_FLAVOR=gnome",
               "--volume", f"{context.resolve()}:/run/context:ro",
               "--volume", f"{ancestry.resolve()}:/proof/ancestor-manifest.json:ro",
               "--volume", f"{evidence.resolve()}:/evidence:rw", image_id, "-c", CHILD]
    completed = None
    failure = None
    stdout = stderr = ""
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=1800)
        stdout, stderr = completed.stdout, completed.stderr
        if completed.returncode:
            failure = f"container exited {completed.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        failure = str(exc)
        stdout = getattr(exc, "stdout", "") or ""
        stderr = getattr(exc, "stderr", "") or ""
    finally:
        # A timed-out Podman client can leave the container alive. Remove only
        # this invocation's named, labelled disposable child, then verify absence.
        try:
            exists = subprocess.run(["podman", "container", "exists", container_name], capture_output=True, timeout=30)
            if exists.returncode == 0:
                details = json.loads(subprocess.check_output(["podman", "container", "inspect", container_name],
                                                             text=True, timeout=30), object_pairs_hook=unique_pairs)
                if (not isinstance(details, list) or len(details) != 1 or not isinstance(details[0], dict)
                        or not isinstance(details[0].get("Config"), dict)
                        or not isinstance(details[0]["Config"].get("Labels"), dict)
                        or details[0]["Config"]["Labels"].get("org.tunaos.package-proof") != container_name):
                    raise ValueError("refuse cleanup: container label does not match this proof")
                subprocess.run(["podman", "rm", "--force", container_name], check=True, capture_output=True, timeout=60)
            elif exists.returncode != 1:
                raise ValueError("cannot determine disposable container status")
            absent = subprocess.run(["podman", "container", "exists", container_name], capture_output=True, timeout=30)
            if absent.returncode != 1:
                raise ValueError("disposable container absence was not verified")
            result["container_cleanup"] = "verified-absent"
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            failure = f"{failure or ''}; cleanup: {exc}"
            result["container_cleanup"] = "unverified"
        for name, data in (("stdout", stdout), ("stderr", stderr)):
            if isinstance(data, bytes):
                data = data.decode(errors="replace")
            (output / (name + ".log")).write_text(data[-1024 * 1024:])
        expected = {"ancestor-package-receipt.json", "package-receipt.json", "stock-baseline.json", "native-removal-receipt.json"}
        evidence_valid = ({path.name for path in evidence.iterdir()} == expected
                          and all(path.is_file() and not path.is_symlink() for path in evidence.iterdir()))
        if not evidence_valid:
            failure = f"{failure or ''}; required evidence is absent or unsafe"
        result["status"] = "failed" if failure else "passed"
        result["exit_code"] = completed.returncode if completed else None
        result["error"] = failure
        result["evidence_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in sorted(evidence.iterdir()) if path.is_file() and not path.is_symlink()}
        receipt.write_text(json.dumps(result, indent=2) + "\n")
    if failure:
        raise ValueError(f"native package proof failed; see {output / 'proof.json'}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--variant", required=True, choices=["grouper", "yellowfin"])
    parser.add_argument("--ancestor-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        qualify(args.image, args.variant, args.ancestor_manifest, args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"optional-removal qualification: {exc}\n")


if __name__ == "__main__":
    main()
