#!/usr/bin/env python3
"""Fail-closed, read-only two-disk preflight helpers for native installer proofs.

No helper creates disks, launches a VM, opens block devices, or authorizes an
installation. The eventual launcher must exclusively create the target in a
private run directory and record its path/st_dev/st_ino immediately. A matching
receipt prevents accidental file substitution; it does not prove provenance or
logical emptiness. Guest signature/partition checks provide separate evidence.

Input facts must be collected successfully in the same paused/pre-confirmation
VM observation window and refreshed immediately before any destructive action.
These snapshots do not prevent TOCTOU, prove absence of concurrent writers, or
replace user authorization. Do not use a saved success receipt as permission.

Expected read-only collectors (not executed here):
  qemu-img info --output=json -- TARGET
  QMP query-block; QMP qom-get(path=each expected qdev, property=serial)
  lsblk --json --bytes --paths --output NAME,KNAME,PATH,TYPE,SIZE,RO,SERIAL,MAJ:MIN,PKNAME,MOUNTPOINTS,FSTYPE,PTTYPE
  findmnt --json --mountpoint / --output TARGET,SOURCE,MAJ:MIN
  readlink -e -- /dev/disk/by-id/virtio-TARGET_SERIAL
  wipefs --no-act --json -- TARGET_KERNEL_PATH

Guest evidence requires a block-backed running root, including a unique nested
ancestry when all lsblk paths are unaliased kernel paths. Overlay/composefs
roots without a block-device root mapping are deliberately unsupported and
fail closed; they need an additional proven root-backing collector before use. Never substitute a guessed /sysroot device.

CLI: python3 scripts/qualify-fork-disk.py --evidence BUNDLE.json
The CLI reads a bundle and host file metadata, then emits a JSON receipt only.
See qualify_disks() for the bundle schema. No installation stage is executed.
"""

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

TARGET_BYTES = 64 * 1024**3
SERIAL = re.compile(r"[A-Za-z0-9_-]{1,20}\Z")
KERNEL_PATH = re.compile(r"/dev/[A-Za-z0-9][A-Za-z0-9_.+-]*\Z")
MAJOR_MINOR = re.compile(r"[0-9]+:[0-9]+\Z")


class DiskQualificationError(ValueError):
    """Missing, inconsistent, or unsafe disk evidence."""


def require(condition, message):
    if not condition:
        raise DiskQualificationError(message)


def object_value(value, label):
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def exact_integer(value, label):
    require(type(value) is int and value >= 0, f"{label} must be a nonnegative integer")
    return value


def canonical_path(value, label):
    require(
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and all(ord(char) >= 32 for char in value),
        f"{label} must be an absolute path",
    )
    path = Path(value)
    require(
        str(path) == value and ".." not in path.parts and value != "/",
        f"{label} must be a canonical non-root path",
    )
    return path


def checked_stat(value, label, *, directory=False):
    """Reject symlinks in every component, never resolve them into permission."""
    path = canonical_path(value, label)
    current = Path("/")
    for component in path.parts[1:]:
        current /= component
        try:
            observed = current.lstat()
        except OSError as error:
            raise DiskQualificationError(f"{label} cannot be inspected: {error}") from error
        require(not stat.S_ISLNK(observed.st_mode), f"{label} contains a symlink")
        if current != path:
            require(stat.S_ISDIR(observed.st_mode), f"{label} ancestor is not a directory")
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    require(expected_type(observed.st_mode), f"{label} has an unsafe file type")
    return path, observed


def validate_host_target(run_directory, source_path, target_path, creation):
    """Check a caller's exclusive-creation receipt against current host identity.

    creation = {method: 'exclusive-new-file', path: str, device: int, inode: int}.
    Only the future launcher can establish the receipt's new-file assertion.
    No qemu image command or filesystem mutation is performed here.
    """
    run, run_stat = checked_stat(run_directory, "run directory", directory=True)
    require(
        run_stat.st_uid == os.geteuid() and stat.S_IMODE(run_stat.st_mode) == 0o700,
        "run directory must be owned by this user with mode 0700",
    )
    source, source_stat = checked_stat(source_path, "source")
    target, target_stat = checked_stat(target_path, "target")
    require(target.parent == run, "target must be a direct child of the private run directory")
    require(target_stat.st_uid == os.geteuid(), "target must be owned by this user")
    require(target_stat.st_nlink == 1, "target must have exactly one hard link")
    require(target_stat.st_mode & 0o077 == 0, "target must not grant group/other access")
    require(
        source != target
        and (source_stat.st_dev, source_stat.st_ino) != (target_stat.st_dev, target_stat.st_ino),
        "source and target must be distinct files",
    )
    creation = object_value(creation, "creation receipt")
    require(creation.get("method") == "exclusive-new-file", "exclusive creation evidence required")
    require(creation.get("path") == str(target), "creation receipt target path mismatch")
    for key, actual in (("device", target_stat.st_dev), ("inode", target_stat.st_ino)):
        require(
            exact_integer(creation.get(key), f"creation {key}") == actual,
            f"creation receipt target {key} mismatch",
        )
    return {
        "path": str(target),
        "device": target_stat.st_dev,
        "inode": target_stat.st_ino,
        "source": {"path": str(source), "device": source_stat.st_dev, "inode": source_stat.st_ino},
    }


def reject_dependencies(value):
    """Reject backing/snapshot/encryption/external-data fields, including nesting."""
    if isinstance(value, dict):
        for key, entry in value.items():
            if key in {
                "backing-filename",
                "full-backing-filename",
                "backing-filename-format",
                "data-file",
            }:
                require(entry == "", f"image has forbidden dependency: {key}")
            if key in {"backing-image", "encrypt"}:
                raise DiskQualificationError(f"image has forbidden dependency: {key}")
            if key == "data-file-raw":
                require(entry is False, "image has an external raw data file")
            if key == "snapshots":
                require(entry == [], "image has snapshots or ambiguous snapshot evidence")
            if key in {"encrypted", "corrupt"}:
                require(entry is False, f"image has unsafe {key} state")
            reject_dependencies(entry)
    elif isinstance(value, list):
        for entry in value:
            reject_dependencies(entry)


def validate_image_info(info, target_path, *, expected_size=TARGET_BYTES):
    """Validate qemu-img/QMP ImageInfo; this does not prove zero-filled content."""
    canonical_path(target_path, "image path")
    info = object_value(info, "image info")
    require(info.get("filename") == target_path, "image filename does not match exact target path")
    require(info.get("format") == "qcow2", "image must be qcow2")
    size = exact_integer(info.get("virtual-size"), "image virtual-size")
    require(expected_size is None or size == expected_size, "image must be exactly 64 GiB")
    require(size > 0, "image has zero virtual size")
    reject_dependencies(info)
    specific = object_value(info.get("format-specific"), "format-specific")
    require(specific.get("type") == "qcow2", "conflicting image format-specific type")
    object_value(specific.get("data"), "format-specific data")
    return {"path": target_path, "format": "qcow2", "virtual_size": size}


def validate_specs(source, target):
    for label, spec in (("source", source), ("target", target)):
        object_value(spec, label)
        canonical_path(spec.get("path"), f"{label} path")
        for key in ("node_name", "qdev"):
            require(
                isinstance(spec.get(key), str)
                and spec[key].strip() == spec[key]
                and bool(spec[key]),
                f"{label} {key} is missing or ambiguous",
            )
        require(
            isinstance(spec.get("serial"), str) and SERIAL.fullmatch(spec["serial"]),
            f"{label} serial must be a safe, untruncated virtio serial (1-20 characters)",
        )
    for key in ("path", "node_name", "qdev", "serial"):
        require(source[key] != target[key], f"source and target {key} must differ")


def validate_qmp_disks(query_block, serial_queries, source, target):
    """Match exactly two QMP disks and their independently queried device serials.

    query_block is the full successful QMP response. serial_queries contains two
    {path: expected qdev, property: 'serial', response: {return: serial}} records.
    Protocol IDs may be present; an error or missing result always fails.
    """
    validate_specs(source, target)
    query_block = object_value(query_block, "query-block response")
    require("error" not in query_block, "query-block failed")
    blocks = query_block.get("return")
    require(
        isinstance(blocks, list) and len(blocks) == 2,
        "query-block must report exactly the source and target disks",
    )
    require(
        isinstance(serial_queries, list) and len(serial_queries) == 2,
        "two QMP serial query results are required",
    )
    remaining = {source["qdev"]: source, target["qdev"]: target}
    receipts = {}
    for block in blocks:
        block = object_value(block, "QMP block")
        qdev = block.get("qdev")
        require(
            isinstance(qdev, str) and qdev in remaining,
            "unexpected or duplicate QMP device mapping",
        )
        spec = remaining.pop(qdev)
        require(block.get("removable") is False, "QMP disk must be non-removable")
        inserted = object_value(block.get("inserted"), "inserted QMP disk")
        require(inserted.get("node-name") == spec["node_name"], "QMP node mapping mismatch")
        require(inserted.get("file") == spec["path"], "QMP host path mapping mismatch")
        require(inserted.get("drv") == "qcow2", "QMP driver must be qcow2")
        require(type(inserted.get("ro")) is bool, "QMP read-only evidence missing")
        require(spec is source or inserted["ro"] is False, "QMP target is read-only")
        require(block.get("io-status", "ok") == "ok", "QMP disk has an I/O error")
        image = validate_image_info(
            inserted.get("image"),
            spec["path"],
            expected_size=TARGET_BYTES if spec is target else None,
        )
        receipts["source" if spec is source else "target"] = {
            **spec,
            "virtual_size": image["virtual_size"],
        }
    remaining = {source["qdev"]: source["serial"], target["qdev"]: target["serial"]}
    for query in serial_queries:
        query = object_value(query, "QMP serial query")
        path = query.get("path")
        require(
            isinstance(path, str) and path in remaining and query.get("property") == "serial",
            "unexpected or duplicate QMP serial query",
        )
        response = object_value(query.get("response"), "QMP serial response")
        require(
            "error" not in response and response.get("return") == remaining.pop(path),
            "QMP device serial mismatch",
        )
    return receipts


def validate_guest_disks(lsblk, root_mount, by_id, wipefs, *, source_serial, target_serial):
    """Validate complete lsblk, findmnt, readlink, and no-act wipefs snapshots.

    by_id = {path, resolved, returncode}; wipefs = {device, returncode, output}.
    Serial-to-QMP correlation is enforced by qualify_disks(), not guessed here.
    """
    require(
        isinstance(source_serial, str)
        and SERIAL.fullmatch(source_serial)
        and isinstance(target_serial, str)
        and SERIAL.fullmatch(target_serial)
        and source_serial != target_serial,
        "source and target serials must be unique and safe",
    )
    roots = object_value(lsblk, "lsblk").get("blockdevices")
    require(
        isinstance(roots, list) and len(roots) == 2,
        "lsblk must report exactly two whole-disk roots",
    )
    seen_paths, seen_numbers, nodes = set(), set(), []

    def visit(node, parent, disk):
        node = object_value(node, "lsblk device")
        path = node.get("path")
        require(
            isinstance(path, str) and KERNEL_PATH.fullmatch(path),
            "lsblk path must be a resolved kernel device path",
        )
        require(
            node.get("name") == path and node.get("kname") == path,
            "lsblk NAME/KNAME/PATH must agree on kernel paths (collect with --paths)",
        )
        require(path not in seen_paths, "duplicate or ambiguous lsblk device ancestry")
        seen_paths.add(path)
        number = node.get("maj:min")
        require(
            isinstance(number, str)
            and MAJOR_MINOR.fullmatch(number)
            and number not in seen_numbers,
            "missing or duplicate lsblk device number",
        )
        seen_numbers.add(number)
        require(
            node.get("type") in ("disk", "part", "crypt", "lvm"),
            "lsblk device type missing or unsupported",
        )
        require(type(node.get("ro")) is bool, "lsblk read-only evidence missing")
        exact_integer(node.get("size"), "lsblk size")
        require(
            "serial" in node and "fstype" in node and "pttype" in node,
            "lsblk serial/filesystem/partition evidence missing",
        )
        require(
            all(
                node[key] is None or isinstance(node[key], str)
                for key in ("serial", "fstype", "pttype")
            ),
            "lsblk serial/filesystem/partition evidence malformed",
        )
        mounts = node.get("mountpoints")
        require(
            isinstance(mounts, list) and all(m is None or isinstance(m, str) for m in mounts),
            "lsblk mountpoints evidence missing",
        )
        require("pkname" in node and node["pkname"] == parent, "lsblk parent mapping mismatch")
        children = node.get("children", [])
        require(isinstance(children, list), "lsblk children evidence malformed")
        nodes.append((node, disk))
        for child in children:
            visit(child, path, disk)

    serial_to_disk = {}
    for disk in roots:
        object_value(disk, "lsblk disk")
        require(disk.get("type") == "disk", "lsblk root must be a whole disk")
        serial = disk.get("serial")
        require(
            isinstance(serial, str)
            and serial in {source_serial, target_serial}
            and serial not in serial_to_disk,
            "unknown or duplicate guest disk serial",
        )
        serial_to_disk[serial] = disk
        visit(disk, None, disk)
    target = serial_to_disk[target_serial]
    source = serial_to_disk[source_serial]
    require(target["size"] == TARGET_BYTES, "guest target must be exactly 64 GiB")
    require(target["ro"] is False, "guest target is read-only")
    require(not target.get("children"), "guest target has partitions or dependent devices")
    require(all(m is None or m == "" for m in target["mountpoints"]), "guest target is mounted")
    require(
        target["fstype"] in (None, "") and target["pttype"] in (None, ""),
        "guest target has filesystem or partition signatures",
    )
    for node, disk in nodes:
        if node is not disk:
            require(
                node["serial"] in (None, "", disk["serial"]), "conflicting child serial evidence"
            )
        require(node is target or node["serial"] != target_serial, "target serial is not unique")
    mounts = object_value(root_mount, "findmnt").get("filesystems")
    require(isinstance(mounts, list) and len(mounts) == 1, "one running-root mount is required")
    root = object_value(mounts[0], "running root")
    require(
        root.get("target") == "/" and not root.get("children"),
        "findmnt must identify exactly the running root",
    )
    matches = [(node, disk) for node, disk in nodes if node["maj:min"] == root.get("maj:min")]
    require(
        len(matches) == 1 and matches[0][1] is source,
        "running root is not proven to belong exclusively to the source disk",
    )
    require(
        root.get("source") == matches[0][0]["path"], "running root source path evidence disagrees"
    )
    require("/" in matches[0][0]["mountpoints"], "running root mount evidence disagrees")
    require(
        all("/" not in node["mountpoints"] or node is matches[0][0] for node, _ in nodes),
        "ambiguous running root mounts",
    )
    by_id = object_value(by_id, "target by-id resolution")
    require(
        type(by_id.get("returncode")) is int and by_id["returncode"] == 0,
        "target by-id resolution did not succeed",
    )
    require(
        by_id.get("path") == f"/dev/disk/by-id/virtio-{target_serial}"
        and by_id.get("resolved") == target["path"],
        "target by-id resolution mismatch",
    )
    wipefs = object_value(wipefs, "wipefs evidence")
    require(
        type(wipefs.get("returncode")) is int and wipefs["returncode"] == 0,
        "wipefs did not succeed",
    )
    require(wipefs.get("device") == target["path"], "wipefs checked the wrong device")
    require(
        object_value(wipefs.get("output"), "wipefs output").get("signatures") == [],
        "wipefs must explicitly report no signatures",
    )
    return {
        "source_path": source["path"],
        "source_serial": source_serial,
        "source_size": source["size"],
        "target_path": target["path"],
        "target_serial": target_serial,
        "target_size": TARGET_BYTES,
        "root_device_number": root["maj:min"],
    }


def qualify_disks(bundle):
    """Validate {source, target, run_directory, creation, image_info, query_block,
    serial_queries, lsblk, root_mount, by_id, wipefs}; return an evidence receipt.
    source/target each require path, node_name, qdev, and serial strings.
    """
    bundle = object_value(bundle, "evidence bundle")
    source = object_value(bundle.get("source"), "source")
    target = object_value(bundle.get("target"), "target")
    validate_specs(source, target)
    host = validate_host_target(
        bundle.get("run_directory"), source["path"], target["path"], bundle.get("creation")
    )
    image = validate_image_info(bundle.get("image_info"), target["path"])
    qmp = validate_qmp_disks(
        bundle.get("query_block"), bundle.get("serial_queries"), source, target
    )
    guest = validate_guest_disks(
        bundle.get("lsblk"),
        bundle.get("root_mount"),
        bundle.get("by_id"),
        bundle.get("wipefs"),
        source_serial=source["serial"],
        target_serial=target["serial"],
    )
    require(
        qmp["source"]["virtual_size"] == guest["source_size"],
        "source size disagrees between QMP and guest evidence",
    )
    # Detect host path substitutions occurring during the remaining validation.
    require(
        host
        == validate_host_target(
            bundle["run_directory"], source["path"], target["path"], bundle["creation"]
        ),
        "host target identity changed",
    )
    return {
        "schema_version": 1,
        "preflight": "passed",
        "installation": "not-run",
        "host_target": host,
        "image": image,
        "qmp": qmp,
        "guest": guest,
    }


def load_evidence(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value):
        raise DiskQualificationError(f"invalid JSON constant: {value}")

    return json.loads(text, object_pairs_hook=unique, parse_constant=reject_constant)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = qualify_disks(load_evidence(args.evidence.read_text()))
    except (DiskQualificationError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print(json.dumps({"preflight": "failed", "installation": "not-run", "error": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
