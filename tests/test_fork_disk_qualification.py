"""Non-destructive guards must reject incomplete or ambiguous disk evidence."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/qualify-fork-disk.py"
SPEC = importlib.util.spec_from_file_location("fork_disk", SCRIPT)
DISK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DISK)


def image(path, size=DISK.TARGET_BYTES):
    return {
        "filename": path,
        "format": "qcow2",
        "virtual-size": size,
        "format-specific": {"type": "qcow2", "data": {"corrupt": False}},
    }


def block(spec):
    return {
        "qdev": spec["qdev"],
        "removable": False,
        "inserted": {
            "file": spec["path"],
            "node-name": spec["node_name"],
            "drv": "qcow2",
            "ro": False,
            "image": image(spec["path"]),
        },
    }


def guest_node(path, *, kind="disk", serial=None, parent=None, mounts=None):
    number = {
        "/dev/vda": "252:0",
        "/dev/vda3": "252:3",
        "/dev/vdb": "252:16",
        "/dev/vdb1": "252:17",
        "/dev/vdc": "252:32",
        "/dev/dm-0": "253:0",
    }[path]
    return {
        "name": path,
        "kname": path,
        "path": path,
        "type": kind,
        "size": DISK.TARGET_BYTES,
        "ro": False,
        "serial": serial,
        "maj:min": number,
        "pkname": parent,
        "mountpoints": mounts or [None],
        "fstype": "ext4" if mounts else None,
        "pttype": None,
    }


@pytest.fixture
def evidence(tmp_path):
    run = tmp_path / "run"
    run.mkdir(mode=0o700)
    # These are tiny fixture files, never actual qcow2 images or block devices.
    source_path, target_path = tmp_path / "source.fixture", run / "target.fixture"
    source_path.write_bytes(b"source")
    target_path.write_bytes(b"target")
    target_path.chmod(0o600)
    target_stat = target_path.stat()
    source = {
        "path": str(source_path),
        "node_name": "source-node",
        "qdev": "/machine/peripheral/source/virtio-backend",
        "serial": "fork-source-123",
    }
    target = {
        "path": str(target_path),
        "node_name": "target-node",
        "qdev": "/machine/peripheral/target/virtio-backend",
        "serial": "fork-target-123",
    }
    source_disk = guest_node("/dev/vda", serial=source["serial"])
    source_disk["children"] = [
        guest_node("/dev/vda3", kind="part", parent="/dev/vda", mounts=["/"])
    ]
    target_disk = guest_node("/dev/vdb", serial=target["serial"])
    return {
        "source": source,
        "target": target,
        "run_directory": str(run),
        "creation": {
            "method": "exclusive-new-file",
            "path": str(target_path),
            "device": target_stat.st_dev,
            "inode": target_stat.st_ino,
        },
        "image_info": image(str(target_path)),
        "query_block": {"return": [block(source), block(target)]},
        "serial_queries": [
            {"path": spec["qdev"], "property": "serial", "response": {"return": spec["serial"]}}
            for spec in (source, target)
        ],
        "lsblk": {"blockdevices": [source_disk, target_disk]},
        "root_mount": {"filesystems": [{"target": "/", "source": "/dev/vda3", "maj:min": "252:3"}]},
        "by_id": {
            "path": "/dev/disk/by-id/virtio-fork-target-123",
            "resolved": "/dev/vdb",
            "returncode": 0,
        },
        "wipefs": {"device": "/dev/vdb", "returncode": 0, "output": {"signatures": []}},
    }


def guest(evidence):
    return DISK.validate_guest_disks(
        evidence["lsblk"],
        evidence["root_mount"],
        evidence["by_id"],
        evidence["wipefs"],
        source_serial=evidence["source"]["serial"],
        target_serial=evidence["target"]["serial"],
    )


def qmp(evidence):
    return DISK.validate_qmp_disks(
        evidence["query_block"], evidence["serial_queries"], evidence["source"], evidence["target"]
    )


def host(evidence):
    return DISK.validate_host_target(
        evidence["run_directory"],
        evidence["source"]["path"],
        evidence["target"]["path"],
        evidence["creation"],
    )


def test_complete_evidence_is_read_only_and_not_installation(evidence):
    before = copy.deepcopy(evidence)
    files = [Path(evidence[role]["path"]) for role in ("source", "target")]
    stats = [p.stat() for p in files]
    result = DISK.qualify_disks(evidence)
    assert result["preflight"] == "passed"
    assert result["installation"] == "not-run"
    assert result["guest"]["target_path"] == "/dev/vdb"
    assert result["guest"]["source_path"] == "/dev/vda"
    assert evidence == before
    assert [p.stat() for p in files] == stats
    assert [p.read_bytes() for p in files] == [b"source", b"target"]


@pytest.mark.parametrize(
    "key",
    [
        "source",
        "target",
        "run_directory",
        "creation",
        "image_info",
        "query_block",
        "serial_queries",
        "lsblk",
        "root_mount",
        "by_id",
        "wipefs",
    ],
)
def test_every_evidence_family_is_required(evidence, key):
    evidence.pop(key)
    with pytest.raises(DISK.DiskQualificationError):
        DISK.qualify_disks(evidence)


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "/",
        "relative",
        "/tmp/../target",
        "/tmp/./target",
        "//tmp/target",
        "/tmp//target",
        "/tmp/target/",
        "/tmp/a\n",
        None,
    ],
)
def test_noncanonical_paths_fail(path):
    with pytest.raises(DISK.DiskQualificationError):
        DISK.canonical_path(path, "target")


@pytest.mark.parametrize(
    "key,value",
    [
        ("virtual-size", 40 * 1024**3),
        ("virtual-size", "68719476736"),
        ("virtual-size", True),
        ("format", "raw"),
        ("filename", "/other"),
        ("backing-filename", "source.qcow2"),
        ("full-backing-filename", "/base"),
        ("backing-image", {}),
        ("snapshots", [{}]),
        ("snapshots", None),
        ("encrypted", True),
        ("corrupt", True),
    ],
)
def test_unsafe_image_metadata_fails(key, value):
    info = image("/run/target")
    info[key] = value
    with pytest.raises(DISK.DiskQualificationError):
        DISK.validate_image_info(info, "/run/target")


@pytest.mark.parametrize(
    "key,value",
    [
        ("data-file", "/other"),
        ("data-file-raw", True),
        ("encrypt", {"format": "luks"}),
        ("corrupt", "false"),
    ],
)
def test_nested_image_dependencies_fail(key, value):
    info = image("/run/target")
    info["format-specific"]["data"][key] = value
    with pytest.raises(DISK.DiskQualificationError):
        DISK.validate_image_info(info, "/run/target")


def test_missing_image_size_and_unknown_format_fail():
    for info in (
        {"filename": "/run/target", "format": "qcow2"},
        {**image("/run/target"), "format-specific": {"type": "raw", "data": {}}},
    ):
        with pytest.raises(DISK.DiskQualificationError):
            DISK.validate_image_info(info, "/run/target")


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777, 0o750])
def test_run_directory_must_be_private(evidence, mode):
    Path(evidence["run_directory"]).chmod(mode)
    with pytest.raises(DISK.DiskQualificationError, match="0700"):
        host(evidence)


def test_target_symlink_rejected(evidence):
    target = Path(evidence["target"]["path"])
    target.unlink()
    target.symlink_to(evidence["source"]["path"])
    with pytest.raises(DISK.DiskQualificationError, match="symlink"):
        host(evidence)


def test_source_symlink_rejected(evidence, tmp_path):
    link = tmp_path / "source-link"
    link.symlink_to(evidence["source"]["path"])
    evidence["source"]["path"] = str(link)
    with pytest.raises(DISK.DiskQualificationError, match="symlink"):
        host(evidence)


def test_ancestor_symlink_rejected(evidence, tmp_path):
    link = tmp_path / "run-link"
    link.symlink_to(evidence["run_directory"], target_is_directory=True)
    evidence["run_directory"] = str(link)
    with pytest.raises(DISK.DiskQualificationError, match="symlink"):
        host(evidence)


def test_target_hardlink_rejected(evidence, tmp_path):
    os.link(evidence["target"]["path"], tmp_path / "alias")
    with pytest.raises(DISK.DiskQualificationError, match="hard link"):
        host(evidence)


def test_source_and_target_same_file_rejected(evidence):
    evidence["source"]["path"] = evidence["target"]["path"]
    with pytest.raises(DISK.DiskQualificationError, match="distinct"):
        host(evidence)


def test_target_outside_run_rejected(evidence, tmp_path):
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    evidence["run_directory"] = str(other)
    with pytest.raises(DISK.DiskQualificationError, match="direct child"):
        host(evidence)


@pytest.mark.parametrize("kind", ["directory", "fifo", "missing", "public"])
def test_unsafe_target_file_types_and_permissions_rejected(evidence, kind):
    target = Path(evidence["target"]["path"])
    if kind == "public":
        target.chmod(0o644)
    else:
        target.unlink()
        if kind == "directory":
            target.mkdir()
        elif kind == "fifo":
            os.mkfifo(target)
    with pytest.raises(DISK.DiskQualificationError):
        host(evidence)


@pytest.mark.parametrize(
    "key,value",
    [
        ("method", "existing-file"),
        ("path", "/other"),
        ("device", -1),
        ("inode", 1),
        ("inode", True),
    ],
)
def test_creation_identity_is_required(evidence, key, value):
    evidence["creation"][key] = value
    with pytest.raises(DISK.DiskQualificationError):
        host(evidence)


def test_replaced_target_identity_rejected(evidence):
    target = Path(evidence["target"]["path"])
    old = target.with_name("old.fixture")
    target.rename(old)
    target.write_bytes(b"replacement")
    target.chmod(0o600)
    with pytest.raises(DISK.DiskQualificationError, match="inode"):
        host(evidence)


@pytest.mark.parametrize("key", ["path", "node_name", "qdev", "serial"])
def test_qmp_source_target_spec_aliases_rejected(evidence, key):
    evidence["target"][key] = evidence["source"][key]
    with pytest.raises(DISK.DiskQualificationError, match="differ"):
        qmp(evidence)


@pytest.mark.parametrize("serial", ["", "x" * 21, "a/b", "a b", None])
def test_ambiguous_or_truncated_serials_rejected(evidence, serial):
    evidence["target"]["serial"] = serial
    with pytest.raises(DISK.DiskQualificationError, match="serial"):
        qmp(evidence)


@pytest.mark.parametrize("change", ["extra", "missing", "duplicate", "error", "empty-medium"])
def test_qmp_requires_exactly_two_mapped_disks(evidence, change):
    blocks = evidence["query_block"]["return"]
    if change == "extra":
        blocks.append(copy.deepcopy(blocks[0]))
    elif change == "missing":
        blocks.pop()
    elif change == "duplicate":
        blocks[1] = copy.deepcopy(blocks[0])
    elif change == "error":
        evidence["query_block"]["error"] = {"desc": "failed"}
    else:
        blocks[1].pop("inserted")
    with pytest.raises(DISK.DiskQualificationError):
        qmp(evidence)


@pytest.mark.parametrize(
    "key,value",
    [("file", "/wrong"), ("node-name", "wrong"), ("drv", "raw"), ("ro", True), ("ro", "false")],
)
def test_qmp_target_mapping_and_state_exact(evidence, key, value):
    evidence["query_block"]["return"][1]["inserted"][key] = value
    with pytest.raises(DISK.DiskQualificationError):
        qmp(evidence)


def test_qmp_source_may_be_read_only_but_cannot_have_backing(evidence):
    source = evidence["query_block"]["return"][0]["inserted"]
    source["ro"] = True
    qmp(evidence)
    source["image"]["backing-filename"] = "/unlisted-source"
    with pytest.raises(DISK.DiskQualificationError, match="dependency"):
        qmp(evidence)


@pytest.mark.parametrize(
    "change", ["wrong-serial", "wrong-device", "wrong-property", "error", "missing"]
)
def test_qmp_serial_correlation_required(evidence, change):
    queries = evidence["serial_queries"]
    if change == "wrong-serial":
        queries[1]["response"]["return"] = evidence["source"]["serial"]
    elif change == "wrong-device":
        queries[1]["path"] = queries[0]["path"]
    elif change == "wrong-property":
        queries[1]["property"] = "other"
    elif change == "error":
        queries[1]["response"]["error"] = {"desc": "failed"}
    else:
        queries.pop()
    with pytest.raises(DISK.DiskQualificationError):
        qmp(evidence)


@pytest.mark.parametrize(
    "key",
    [
        "name",
        "kname",
        "path",
        "type",
        "size",
        "ro",
        "serial",
        "maj:min",
        "pkname",
        "mountpoints",
        "fstype",
        "pttype",
    ],
)
def test_guest_target_requires_all_safety_columns(evidence, key):
    evidence["lsblk"]["blockdevices"][1].pop(key)
    with pytest.raises(DISK.DiskQualificationError):
        guest(evidence)


@pytest.mark.parametrize(
    "key,value",
    [
        ("size", 40 * 1024**3),
        ("size", "68719476736"),
        ("ro", True),
        ("ro", 0),
        ("mountpoints", ["/mnt"]),
        ("mountpoints", ["[SWAP]"]),
        ("fstype", "ext4"),
        ("pttype", "gpt"),
        ("type", "part"),
        ("children", None),
        ("pkname", "/dev/vda"),
        ("maj:min", "252:0"),
        ("serial", "fork-source-123"),
    ],
)
def test_guest_unsafe_target_rejected(evidence, key, value):
    evidence["lsblk"]["blockdevices"][1][key] = value
    with pytest.raises(DISK.DiskQualificationError):
        guest(evidence)


def test_target_partition_rejected(evidence):
    evidence["lsblk"]["blockdevices"][1]["children"] = [
        guest_node("/dev/vdb1", kind="part", parent="/dev/vdb")
    ]
    with pytest.raises(DISK.DiskQualificationError, match="partitions"):
        guest(evidence)


def test_guest_name_is_resolved_not_assumed_vdb(evidence):
    target = evidence["lsblk"]["blockdevices"][1]
    for key in ("name", "kname", "path"):
        target[key] = "/dev/vdc"
    target["maj:min"] = "252:32"
    evidence["by_id"]["resolved"] = "/dev/vdc"
    evidence["wipefs"]["device"] = "/dev/vdc"
    evidence["lsblk"]["blockdevices"].reverse()
    assert guest(evidence)["target_path"] == "/dev/vdc"


def test_running_target_is_rejected(evidence):
    evidence["root_mount"]["filesystems"][0].update({"source": "/dev/vdb", "maj:min": "252:16"})
    with pytest.raises(DISK.DiskQualificationError, match="source disk"):
        guest(evidence)


@pytest.mark.parametrize(
    "key,value",
    [("target", "/sysroot"), ("source", "/dev/other"), ("maj:min", "0:26"), ("maj:min", None)],
)
def test_unproven_running_source_rejected(evidence, key, value):
    evidence["root_mount"]["filesystems"][0][key] = value
    with pytest.raises(DISK.DiskQualificationError):
        guest(evidence)


def test_unique_nested_source_ancestry_can_pass(evidence):
    partition = evidence["lsblk"]["blockdevices"][0]["children"][0]
    partition["mountpoints"] = [None]
    partition["children"] = [
        guest_node("/dev/dm-0", kind="crypt", parent="/dev/vda3", mounts=["/"])
    ]
    evidence["root_mount"]["filesystems"][0].update({"source": "/dev/dm-0", "maj:min": "253:0"})
    assert guest(evidence)["root_device_number"] == "253:0"


def test_duplicate_ancestry_rejected(evidence):
    root_disk = evidence["lsblk"]["blockdevices"][0]
    root_disk["children"].append(copy.deepcopy(root_disk["children"][0]))
    with pytest.raises(DISK.DiskQualificationError, match="duplicate"):
        guest(evidence)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("by_id", "path", "/dev/disk/by-id/virtio-fork-source-123"),
        ("by_id", "resolved", "/dev/vda"),
        ("by_id", "returncode", 1),
        ("by_id", "returncode", False),
        ("wipefs", "device", "/dev/vda"),
        ("wipefs", "returncode", 1),
        ("wipefs", "returncode", False),
        ("wipefs", "output", {}),
        ("wipefs", "output", {"signatures": None}),
        ("wipefs", "output", {"signatures": [{"type": "gpt"}]}),
    ],
)
def test_by_id_and_wipefs_must_prove_exact_target(evidence, section, key, value):
    evidence[section][key] = value
    with pytest.raises(DISK.DiskQualificationError):
        guest(evidence)


@pytest.mark.parametrize(
    "text", ['{"a":1,"a":2}', '{"a":{"b":1,"b":2}}', '{"a":NaN}', '{"a":Infinity}']
)
def test_ambiguous_json_rejected(text):
    with pytest.raises(DISK.DiskQualificationError):
        DISK.load_evidence(text)


def test_cli_pass_and_fail_are_truthful(evidence, tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--evidence", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["installation"] == "not-run"
    evidence["wipefs"]["output"]["signatures"] = [{"type": "gpt"}]
    path.write_text(json.dumps(evidence))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--evidence", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["preflight"] == "failed"
    assert json.loads(result.stdout)["installation"] == "not-run"


def test_cli_does_not_execute_collection_or_mutating_commands():
    text = SCRIPT.read_text()
    assert "import subprocess" not in text
    assert "os.system" not in text
    assert "subprocess." not in text


@pytest.mark.parametrize("bad_path", ["/dev/.", "/dev/..", "/dev/disk/by-id/alias", "vdb"])
def test_guest_kernel_aliases_rejected(evidence, bad_path):
    target = evidence["lsblk"]["blockdevices"][1]
    target.update({key: bad_path for key in ("name", "kname", "path")})
    with pytest.raises(DISK.DiskQualificationError, match="kernel device"):
        guest(evidence)


def test_qmp_disagrees_with_image_header_filename(evidence):
    evidence["query_block"]["return"][1]["inserted"]["image"]["filename"] = evidence["source"][
        "path"
    ]
    with pytest.raises(DISK.DiskQualificationError, match="filename"):
        qmp(evidence)


def test_host_source_substitution_during_validation_rejected(evidence, monkeypatch):
    original = DISK.validate_guest_disks

    def replace_source(*args, **kwargs):
        source = Path(evidence["source"]["path"])
        source.rename(source.with_name("previous-source.fixture"))
        source.write_bytes(b"changed-source")
        return original(*args, **kwargs)

    monkeypatch.setattr(DISK, "validate_guest_disks", replace_source)
    with pytest.raises(DISK.DiskQualificationError, match="identity changed"):
        DISK.qualify_disks(evidence)


def test_source_root_requires_matching_mount_observation(evidence):
    evidence["lsblk"]["blockdevices"][0]["children"][0]["mountpoints"] = [None]
    with pytest.raises(DISK.DiskQualificationError, match="mount evidence"):
        guest(evidence)


def test_second_running_root_mount_is_ambiguous(evidence):
    evidence["lsblk"]["blockdevices"][0]["mountpoints"] = ["/"]
    with pytest.raises(DISK.DiskQualificationError, match="ambiguous running root"):
        guest(evidence)


def test_additional_guest_disk_is_rejected(evidence):
    evidence["lsblk"]["blockdevices"].append(guest_node("/dev/vdc", serial="other"))
    with pytest.raises(DISK.DiskQualificationError, match="exactly two"):
        guest(evidence)


def test_missing_root_mount_result_is_rejected(evidence):
    evidence["root_mount"]["filesystems"] = []
    with pytest.raises(DISK.DiskQualificationError, match="running-root"):
        guest(evidence)


def test_serial_reuse_under_source_is_rejected(evidence):
    evidence["lsblk"]["blockdevices"][0]["children"][0]["serial"] = evidence["target"]["serial"]
    with pytest.raises(DISK.DiskQualificationError, match="serial"):
        guest(evidence)


@pytest.mark.parametrize(
    "key,value",
    [
        ("backing-filename", None),
        ("backing-filename", False),
        ("data-file", None),
        ("encrypt", None),
        ("format-specific", None),
    ],
)
def test_unknown_dependency_metadata_fails_closed(key, value):
    info = image("/run/target")
    info[key] = value
    with pytest.raises(DISK.DiskQualificationError):
        DISK.validate_image_info(info, "/run/target")


def test_format_specific_evidence_cannot_be_omitted():
    info = image("/run/target")
    info.pop("format-specific")
    with pytest.raises(DISK.DiskQualificationError, match="format-specific"):
        DISK.validate_image_info(info, "/run/target")


def test_source_size_must_agree_across_host_and_guest(evidence):
    evidence["query_block"]["return"][0]["inserted"]["image"]["virtual-size"] += 1024
    with pytest.raises(DISK.DiskQualificationError, match="source size disagrees"):
        DISK.qualify_disks(evidence)
