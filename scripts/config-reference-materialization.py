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
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reference_config_recipe", ROOT / "scripts/config-only-image-qualification.py"
)
RECIPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECIPE)
ROLE = "modifiedDesktop"
ARCHIVE = "reference-desktop.oci.tar"


def need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


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


def retain(root: Path, plan_path: Path, output: Path, family: str) -> dict:
    need(not root.is_symlink(), "source: expected a real checkout")
    root = root.resolve()
    plan = RECIPE.read_json(plan_path)
    selected_build(plan, family)
    need(not output.exists() and not any(parent.is_symlink() for parent in (output, *output.parents)),
         "output: refusing existing evidence or a symlinked path")
    need(not output.resolve().is_relative_to(root), "output: must be outside the source checkout")
    output.mkdir(parents=True)
    source = RECIPE._source_record(plan, root, output / "source-inspection.log")
    cell = next(item for item in plan["families"] if item["family"] == family)
    with RECIPE._HARNESS.CommandLog(output / "image-inspection.log") as log:
        image = RECIPE._image_record(plan, cell, ROLE, root, log)
        apt_proof = apt_image_proof(root, image, log) if family == "apt" else None
        need(image["branding"]["status"] == "passed" and image["packageStatus"] == "installed",
             "image: configured brand or package inspection failed")
        # Preserve the observed manifest instead of converting/recompressing it.
        # Copy by immutable storage ID, not the mutable localhost tag.
        RECIPE._HARNESS.checked(log, [
            "skopeo", "copy", "--preserve-digests",
            "containers-storage:" + image["imageId"],
            "oci-archive:" + str(output / ARCHIVE) + ":customized-reference",
        ], what="retain exact customized desktop bytes")
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
    keep = sub.add_parser("retain")
    keep.add_argument("--source", type=Path, required=True)
    keep.add_argument("--plan", type=Path, required=True)
    keep.add_argument("--output", type=Path, required=True)
    keep.add_argument("--family", choices=("rpm", "apt"), required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--receipt-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            RECIPE.prepare(args.source, args.plan)
            result = selected_build(RECIPE.read_json(args.plan), args.family)
        elif args.command == "retain":
            result = retain(args.source, args.plan, args.output, args.family)
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
