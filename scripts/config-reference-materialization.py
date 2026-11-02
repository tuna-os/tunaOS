#!/usr/bin/env python3
"""Materialize one customized reference image, not lifecycle qualification.

Reuse the accepted config-only recipe and image inspector. No registry push,
media build, VM, update, or qualification verdict is performed by this adapter.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reference_config_recipe", ROOT / "scripts/config-only-image-qualification.py"
)
RECIPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECIPE)
ROLE = "modifiedDesktop"
ARCHIVE = "reference-desktop.oci.tar"
FREE_FLOOR = 40 * 1024**3
# Forwarded through the build engine's existing BUILDAH_CACHE_FLAGS seam.
# These constrain RUN containers directly, not just a possibly escaped parent.
BUILD_FLAGS = "--layers --isolation=oci --memory=8g --memory-swap=8g --cpu-period=100000 --cpu-quota=200000"


def need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def archive_budget(raw_manifest: bytes, image: dict) -> dict:
    """Bound export storage from the exact manifest, including OCI tar staging."""
    need(0 < len(raw_manifest) <= 1024**2, "export: manifest exceeds JSON bound")
    need(RECIPE.sha256(raw_manifest) == image["manifestDigest"], "export: manifest identity changed")
    manifest = json.loads(raw_manifest, object_pairs_hook=RECIPE._HARNESS.unique_object)
    need(isinstance(manifest, dict) and manifest.get("schemaVersion") == 2
         and isinstance(manifest.get("layers"), list) and manifest["layers"],
         "export: expected an image manifest")
    sizes = {image["manifestDigest"]: len(raw_manifest)}
    for descriptor in [manifest.get("config"), *manifest["layers"]]:
        need(isinstance(descriptor, dict) and isinstance(descriptor.get("digest"), str)
             and RECIPE.DIGEST.fullmatch(descriptor["digest"])
             and ("urls" not in descriptor or descriptor["urls"] == [])
             and type(descriptor.get("size")) is int and 0 < descriptor["size"] <= 2**63 - 1,
             "export: invalid blob descriptor")
        digest, size = descriptor["digest"], descriptor["size"]
        need(digest not in sizes, "export: duplicate blob descriptor")
        sizes[digest] = size
    need(manifest["config"]["digest"] == image["configDigest"], "export: config identity changed")
    # Fixed digest paths fit tar's name field. A large blob can need a PAX
    # size record: up to three 512-byte blocks per file. Include directories,
    # the two <=1MiB JSON documents already bounded by verify_archive, and
    # a complete 10KiB tar end block.
    payload = sum(sizes.values())
    padding = sum((-size) % 512 for size in sizes.values())
    overhead = (len(sizes) + 8) * 1536 + 2 * 1024**2 + 10240
    archive_bound = payload + padding + overhead
    largest_layer = max(item["size"] for item in manifest["layers"])
    peak = 2 * archive_bound + largest_layer
    need(0 < archive_bound <= 2**63 - 1 and 0 < peak <= 2**63 - 1,
         "export: byte budget overflow")
    return {
        "payloadBytes": payload, "uniqueBlobs": len(sizes),
        "tarPaddingBytes": padding, "tarAndMetadataBudgetBytes": overhead,
        "archiveBytesUpperBound": archive_bound,
        # OCI archive destinations stage a complete OCI layout before making
        # the tar. Also reserve one largest-layer scratch, never just final tar.
        "copyPeakAdditionalBytes": peak,
    }


def require_free_bytes(available: int, additional: int) -> int:
    need(type(available) is int and available >= 0 and type(additional) is int
         and 0 <= additional <= 2**63 - 1 - FREE_FLOOR, "storage: invalid export requirement")
    required = FREE_FLOOR + additional
    need(available >= required,
         f"storage: {available} bytes available; need {required} including 40GiB headroom")
    return required


def resource_path(raw: bytes, group: str, field: str) -> str:
    need(0 < len(raw) <= 1024**2, "storage: resource metadata exceeds JSON bound")
    value = json.loads(raw, object_pairs_hook=RECIPE._HARNESS.unique_object)
    records = value.get(group) if isinstance(value, dict) else None
    need(isinstance(records, list) and len(records) == 1 and isinstance(records[0], dict),
         "storage: expected one actual backing resource")
    path = records[0].get(field)
    need(isinstance(path, str) and path.startswith("/") and len(path) <= 4096 and "\0" not in path,
         "storage: unavailable or unsupported backing path")
    return path


def allocation_devices(output_device: int, backing: dict[int, int]) -> set[int]:
    """Charge copies to sparse filesystems and every physical backing ancestor."""
    charged = {output_device}
    while True:
        ancestors = {backing[device] for device in charged if device in backing}
        if ancestors <= charged:
            break
        charged.update(ancestors)
    need(any(device not in backing for device in charged), "storage: cyclic sparse backing mapping")
    return charged


def storage_preflight(root: Path, output: Path, log, additional: int = 0) -> dict:
    """Check actual output/store/backing filesystems, not a sparse loop's capacity."""
    need(os.environ.get("GITHUB_ACTIONS") == "true"
         and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted",
         "resources: native materialization is hosted-only; no local build/proof authorization")
    need(os.geteuid() == 0, "resources: rootful OCI runtime is required")
    controllers_path = Path("/sys/fs/cgroup/cgroup.controllers")
    need(controllers_path.is_file(), "resources: cgroup v2 is required for OCI limits")
    controllers = set(controllers_path.read_text().split())
    need({"cpu", "memory"} <= controllers, "resources: CPU/memory controllers are unavailable")
    store_raw = RECIPE._HARNESS.checked(log, [
        "podman", "info", "--format", "{{.Store.GraphRoot}}",
    ], what="actual rootful storage").decode().strip()
    need(store_raw.startswith("/") and len(store_raw) <= 4096, "storage: invalid graph root")
    store = Path(store_raw)
    need(store.is_dir(), "storage: rootful graph root is unavailable")
    paths = [root, output.parent, store]
    mounts = set()
    backing_devices = {}
    cursor = 0
    while cursor < len(paths):
        path = paths[cursor]
        cursor += 1
        device = path.stat().st_dev
        if device in mounts:
            continue
        mounts.add(device)
        source = resource_path(RECIPE._HARNESS.checked(log, [
            "findmnt", "--json", "--target", str(path), "--output", "SOURCE",
        ], what="actual allocation mount"), "filesystems", "source")
        if source.startswith("/dev/loop"):
            backing = Path(resource_path(RECIPE._HARNESS.checked(log, [
                "losetup", "--json", "--output", "BACK-FILE", "--list", source,
            ], what="sparse allocation backing file"), "loopdevices", "back-file"))
            need(backing.is_file() and backing.stat().st_dev != device,
                 "storage: sparse backing file is unavailable or recursive")
            backing_devices[device] = backing.stat().st_dev
            paths.append(backing)
    copy_devices = allocation_devices(output.parent.stat().st_dev, backing_devices)
    disks = {}
    for path in paths:
        device = path.stat().st_dev
        if device in disks:
            continue
        usage = os.statvfs(path)
        available = usage.f_bavail * usage.f_frsize
        required = require_free_bytes(available, additional if device in copy_devices else 0)
        disks[device] = {"device": device, "availableBytes": available, "requiredBytes": required}
    memory = {line.split(":")[0]: int(line.split()[1]) * 1024
              for line in Path("/proc/meminfo").read_text().splitlines()
              if line.startswith(("MemTotal:", "MemAvailable:"))}
    need(set(memory) == {"MemTotal", "MemAvailable"}, "resources: actual VM memory is unavailable")
    return {
        "freeFloorBytes": FREE_FLOOR, "additionalCopyBytes": additional,
        "filesystems": list(disks.values()), "buildahFlags": BUILD_FLAGS,
        "requested": {"isolation": "oci", "runMemoryBytes": 8 * 1024**3,
                      "runMemoryAndSwapBytes": 8 * 1024**3,
                      "runCpuPeriod": 100000, "runCpuQuota": 200000},
        "enforced": {"status": "not-observed", "requiresOCIRuntime": True},
        "hostedRunner": {
            "environment": os.environ["RUNNER_ENVIRONMENT"], "logicalCPUs": os.cpu_count(),
            "availableCPUs": len(os.sched_getaffinity(0)),
            "memoryTotalBytes": memory["MemTotal"], "memoryAvailableBytes": memory["MemAvailable"],
            "availableControllers": sorted(controllers),
        },
        "limitScope": "Buildah RUN containers; hosted VM remains the aggregate boundary, not a claimed local 8GiB cgroup",
    }


def build_preflight(root: Path, output: Path) -> dict:
    with RECIPE._HARNESS.CommandLog(output.parent / ".build-resource-preflight.log") as log:
        resources = storage_preflight(root, output, log)
        resources["buildahVersion"] = RECIPE._HARNESS.checked(
            log, ["buildah", "--version"], what="actual buildah version",
        ).decode().strip()
    resources["sourceCommit"] = RECIPE.git(root, "rev-parse", "HEAD")
    resources["reviewedWorkflowCommit"] = os.environ.get("GITHUB_SHA")
    need(isinstance(resources["reviewedWorkflowCommit"], str)
         and RECIPE.COMMIT.fullmatch(resources["reviewedWorkflowCommit"]),
         "resources: missing reviewed workflow commit")
    return resources


def selected_build(plan: dict, family: str) -> dict:
    """The selected GNOME target builds its base stage internally."""
    RECIPE.validate_plan(plan)
    need(family in {"rpm", "apt"}, "family: expected rpm or apt")
    variant = "yellowfin" if family == "rpm" else "grouper"
    records = [item for item in plan["builds"] if item["family"] == family and item["role"] == ROLE]
    need(len(records) == 1, "plan: expected one customized reference desktop build")
    build = records[0]
    need(build["variant"] == variant and build["flavor"] == "gnome"
         and build["commit"] == plan["modifiedCommit"] and build["chain"] == "",
         "plan: expected a native GNOME target without a parent override")
    return build


def verify_archive(path: Path, image: dict) -> dict:
    """Check retained bytes, without extracting paths or trusting an image tag."""
    need(isinstance(image, dict), "archive: missing inspected image identity")
    for key in ("manifestDigest", "configDigest"):
        need(isinstance(image.get(key), str) and RECIPE.DIGEST.fullmatch(image[key]),
             "archive: missing immutable image digest")
    with tarfile.open(path, "r:") as archive:
        members = {}
        for member in archive:
            name = member.name.removeprefix("./")
            need(name not in members, "archive: duplicate member")
            need(member.isdir() or member.isfile(), "archive: links and special files are forbidden")
            need(not name.startswith("/") and ".." not in Path(name).parts,
                 "archive: unsafe member path")
            members[name] = member

        def blob(name: str, *, document: bool = False) -> bytes | None:
            member = members.get(name)
            need(member is not None and member.isfile(), f"archive: missing {name}")
            if document:
                need(member.size <= 1024 * 1024, "archive: oversized JSON document")
            with archive.extractfile(member) as stream:
                if document:
                    return stream.read()
                actual = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
            need(actual == "sha256:" + name.rsplit("/", 1)[1], "archive: blob hash mismatch")
            return None

        def document(name: str) -> dict:
            raw = blob(name, document=True)
            if name.startswith("blobs/"):
                need(RECIPE.sha256(raw) == "sha256:" + name.rsplit("/", 1)[1],
                     "archive: document hash mismatch")
            value = json.loads(raw, object_pairs_hook=RECIPE._HARNESS.unique_object)
            need(isinstance(value, dict), "archive: expected a JSON object")
            return value

        layout = document("oci-layout")
        need(layout == {"imageLayoutVersion": "1.0.0"}, "archive: invalid OCI layout")
        index = document("index.json")
        manifests = index.get("manifests")
        need(index.get("schemaVersion") == 2 and isinstance(manifests, list) and len(manifests) == 1,
             "archive: expected exactly one image manifest")

        def descriptor(value: dict, expected: str | None = None) -> str:
            need(isinstance(value, dict) and isinstance(value.get("digest"), str)
                 and RECIPE.DIGEST.fullmatch(value["digest"]),
                 "archive: invalid descriptor digest")
            need(type(value.get("size")) is int and value["size"] > 0,
                 "archive: invalid descriptor size")
            digest = value["digest"]
            need(expected is None or digest == expected, "archive: immutable image identity changed")
            name = "blobs/sha256/" + digest.removeprefix("sha256:")
            member = members.get(name)
            need(member is not None and member.size == value["size"], "archive: descriptor size mismatch")
            return name
        manifest = document(descriptor(manifests[0], image["manifestDigest"]))
        need(manifest.get("schemaVersion") == 2, "archive: invalid image manifest")
        config = document(descriptor(manifest.get("config"), image["configDigest"]))
        need(config.get("os") == "linux" and config.get("architecture") == "amd64",
             "archive: expected linux/amd64")
        layers = manifest.get("layers")
        need(isinstance(layers, list) and layers, "archive: missing image layers")
        for layer in layers:
            blob(descriptor(layer))
    return {"file": path.name, "sha256": file_digest(path), "sizeBytes": path.stat().st_size,
            "manifestDigest": image["manifestDigest"], "configDigest": image["configDigest"]}


def apt_image_proof(root: Path, image: dict, log) -> dict:
    """Run the APT owner's static consumer checks in the exact inspected image."""
    raw = RECIPE._HARNESS.checked(log, [
        "podman", "run", "--rm", "--pull=never", "--network=none",
        "--security-opt=no-new-privileges", "--cap-drop=all",
        "--volume", f"{root}:/proof:ro", "--entrypoint", "python3",
        image["imageId"], "/proof/scripts/verify-apt-reference.py", "--root", "/",
    ], what="APT reference static consumer proof")
    need(0 < len(raw) <= 32 * 1024, "APT proof: expected bounded JSON")
    proof = json.loads(raw, object_pairs_hook=RECIPE._HARNESS.unique_object)
    need(isinstance(proof, dict) and proof.get("schemaVersion") == 1
         and proof.get("purpose") == "apt-image-static-proof-only"
         and proof.get("family") == "apt" and proof.get("variant") == "grouper"
         and proof.get("desktop") == "gnome" and proof.get("platform") == "linux/amd64"
         and proof.get("runtimeAcceptance") == "not-run",
         "APT proof: target or static-only scope mismatch")
    need(proof.get("backend") == {
        "bootloader": "systemd", "composeFsBackend": True, "filesystem": "ext4",
    }, "APT proof: unsupported installed backend")
    kernel = proof.get("kernel")
    need(isinstance(kernel, dict) and isinstance(kernel.get("version"), str) and kernel["version"],
         "APT proof: missing installed kernel identity")
    for key in ("vmlinuzSha256", "configSha256", "initramfsSha256"):
        need(isinstance(kernel.get(key), str) and RECIPE.DIGEST.fullmatch(kernel[key]),
             "APT proof: missing installed kernel byte identity")
    brand = proof.get("branding")
    need(isinstance(brand, dict) and brand.get("status") == "passed"
         and brand.get("checkerSha256") == file_digest(root / "build_scripts/checks/verify-plymouth-initramfs.sh"),
         "APT proof: branding checker identity mismatch")
    return proof


def retain(root: Path, plan_path: Path, output: Path, family: str, build_resources: Path) -> dict:
    need(not root.is_symlink(), "source: expected a real checkout")
    root = root.resolve()
    plan = RECIPE.read_json(plan_path)
    selected_build(plan, family)
    build_safety = RECIPE.read_json(build_resources)
    need(isinstance(build_safety, dict) and build_safety.get("sourceCommit") == plan["modifiedCommit"]
         and build_safety.get("reviewedWorkflowCommit") == plan["stockCommit"]
         and build_safety.get("buildahFlags") == BUILD_FLAGS,
         "resources: pre-build receipt differs from source or Buildah limit request")
    need(not output.exists() and not any(parent.is_symlink() for parent in (output, *output.parents)),
         "output: refusing existing evidence or a symlinked path")
    need(not output.resolve().is_relative_to(root), "output: must be outside the source checkout")
    output.mkdir(parents=True)
    source = RECIPE._source_record(plan, root, output / "source-inspection.log")
    cell = next(item for item in plan["families"] if item["family"] == family)
    with RECIPE._HARNESS.CommandLog(output / "image-inspection.log") as log:
        storage_preflight(root, output, log)
        image = RECIPE._image_record(plan, cell, ROLE, root, log)
        apt_proof = apt_image_proof(root, image, log) if family == "apt" else None
        need(image["branding"]["status"] == "passed" and image["packageStatus"] == "installed",
             "image: configured brand or package inspection failed")
        # Size the exact immutable manifest before duplicating any image bytes.
        raw_manifest = RECIPE._HARNESS.checked(log, [
            "skopeo", "inspect", "--raw", "containers-storage:" + image["imageId"],
        ], what="immutable export manifest")
        budget = archive_budget(raw_manifest, image)
        export_skopeo_version = RECIPE._HARNESS.checked(
            log, ["skopeo", "--version"], what="actual export transport version",
        ).decode().strip()
        export_safety = storage_preflight(root, output, log, budget["copyPeakAdditionalBytes"])
        export_safety["skopeoVersion"] = export_skopeo_version
        # Both the staged OCI layout and archive use the checked filesystem.
        with tempfile.TemporaryDirectory(prefix=".export-", dir=output) as scratch:
            RECIPE._HARNESS.checked(log, [
                "env", f"TMPDIR={scratch}", "skopeo", "--tmpdir", scratch,
                "copy", "--preserve-digests", "containers-storage:" + image["imageId"],
                "oci-archive:" + str(output / ARCHIVE) + ":customized-reference",
            ], what="retain exact customized desktop bytes")
        need((output / ARCHIVE).stat().st_size <= budget["archiveBytesUpperBound"],
             "export: archive exceeded descriptor-derived upper bound")
        storage_preflight(root, output, log)
    archive = verify_archive(output / ARCHIVE, image)
    bundle = output / "customized-source.bundle"
    RECIPE.git(root, "bundle", "create", str(bundle), "HEAD", "^" + plan["stockCommit"])
    (output / "config-only-image-plan.json").write_bytes(plan_path.read_bytes())
    receipt = {
        "purpose": "reference-image-materialization-only", "family": family,
        "platform": "linux/amd64", "variant": cell["variant"], "desktop": "gnome",
        "stockCommit": plan["stockCommit"], "modifiedCommit": plan["modifiedCommit"],
        "configSha256": plan["modifiedConfigSha256"], "planSha256": file_digest(plan_path),
        "source": source, "image": image, "desktopArchive": archive,
        "sourceBundle": {"file": bundle.name, "sha256": file_digest(bundle),
                         "prerequisiteCommit": plan["stockCommit"]},
        "aptImageProof": apt_proof,
        "resources": {"build": build_safety, "export": export_safety, "archiveBudget": budget},
        "runtime": {stage: "not-run" for stage in (
            "media", "boot", "login", "visible-brand", "offline-gui-install",
            "detached-boot", "update", "recovery")},
    }
    (output / "materialization.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def verify_materialization(receipt_path: Path, archive: Path, receipt_sha256: str) -> dict:
    need(file_digest(receipt_path) == receipt_sha256, "receipt: expected independently recorded SHA-256")
    receipt = RECIPE.read_json(receipt_path)
    need(isinstance(receipt, dict) and receipt.get("purpose") == "reference-image-materialization-only",
         "receipt: not reference image materialization")
    family = receipt.get("family")
    need(family in {"rpm", "apt"}, "receipt: unsupported family")
    image = receipt.get("image")
    need(isinstance(image, dict) and image.get("role") == ROLE and image.get("platform") == "linux/amd64",
         "receipt: expected an immutable reference desktop image")
    expected_variant = "yellowfin" if family == "rpm" else "grouper"
    need(receipt.get("variant") == expected_variant and receipt.get("desktop") == "gnome"
         and receipt.get("platform") == "linux/amd64",
         "receipt: target mismatch")
    need(isinstance(receipt.get("modifiedCommit"), str)
         and RECIPE.COMMIT.fullmatch(receipt["modifiedCommit"])
         and image.get("sourceCommit") == receipt["modifiedCommit"]
         and image.get("configSha256") == receipt.get("configSha256"),
         "receipt: source/config identity mismatch")
    retained = receipt.get("desktopArchive")
    need(isinstance(retained, dict) and set(retained) == {
        "file", "sha256", "sizeBytes", "manifestDigest", "configDigest",
    }, "archive: invalid retained byte identity")
    need(type(retained["sizeBytes"]) is int and retained["sizeBytes"] > 0
         and isinstance(retained["sha256"], str) and RECIPE.DIGEST.fullmatch(retained["sha256"]),
         "archive: invalid retained size or SHA-256")
    need(retained["file"] == archive.name
         and retained["manifestDigest"] == image.get("manifestDigest")
         and retained["configDigest"] == image.get("configDigest"),
         "archive: retained image identity differs from receipt")
    # Authenticate downloaded bytes before tarfile can interpret an attacker-
    # controlled PAX length. Member/JSON bounds run too late to protect parsing.
    need(archive.stat().st_size == retained["sizeBytes"], "archive: retained byte size differs from receipt")
    need(file_digest(archive) == retained["sha256"], "archive: retained byte hash differs from receipt")
    actual = verify_archive(archive, image)
    need(actual == receipt.get("desktopArchive"), "archive: retained bytes differ from receipt")
    return actual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--plan", type=Path, required=True)
    prepare.add_argument("--family", choices=("rpm", "apt"), required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--source", type=Path, required=True)
    preflight.add_argument("--output", type=Path, required=True)
    keep = sub.add_parser("retain")
    keep.add_argument("--source", type=Path, required=True)
    keep.add_argument("--plan", type=Path, required=True)
    keep.add_argument("--output", type=Path, required=True)
    keep.add_argument("--family", choices=("rpm", "apt"), required=True)
    keep.add_argument("--build-resources", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--receipt-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            RECIPE.prepare(args.source, args.plan)
            result = selected_build(RECIPE.read_json(args.plan), args.family)
        elif args.command == "preflight":
            result = build_preflight(args.source, args.output)
        elif args.command == "retain":
            result = retain(args.source, args.plan, args.output, args.family, args.build_resources)
        else:
            result = verify_materialization(args.receipt, args.archive, args.receipt_sha256)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, tarfile.TarError, RECIPE.QualificationError,
            RECIPE._HARNESS.QualificationError, RECIPE.tunaos_config.ConfigError) as exc:
        print(f"ERROR: reference materialization: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
