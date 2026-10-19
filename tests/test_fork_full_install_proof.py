"""Full-install safety gates use observed source/target identity, never UI success alone.

All guest calls and QMP responses are mocked. Tiny files stand in for host disk
metadata: these tests never launch guests, create real disks, authenticate, or
execute installer/recipe mutation programs.
"""

import copy
import importlib.util
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "full_install_proof", ROOT / "scripts/qualify-fork-install.py"
)
PROOF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROOF)
SOURCE_BOOT = "11111111-1111-1111-1111-111111111111"
TARGET_BOOT = "22222222-2222-2222-2222-222222222222"
OBSERVER_SHA = "a" * 64


def receipt():
    return {
        "schema_version": 1,
        "target_imgref": "localhost/fork-qualification/yellowfin:gnome-linux-amd64",
        "original_local_imgref": "containers-storage:localhost/fork-qualification/yellowfin:gnome-linux-amd64",
        "source_image_id": "sha256:" + "b" * 64,
        "source_manifest_digest": "sha256:" + "c" * 64,
        "fork_manifest_sha256": "sha256:" + "d" * 64,
        "recipe_sha256": "sha256:" + "e" * 64,
        "catalog_sha256": "sha256:" + "f" * 64,
        "storage": {"composeFsBackend": False, "bootloader": "grub2", "filesystem": "xfs"},
        "preserved_digest": True,
        "verified_oci": {
            "config_digest": "sha256:" + "b" * 64,
            "manifest_digest": "sha256:" + "c" * 64,
        },
    }


def recipe():
    source = receipt()
    return {
        "disk": "/dev/vdb",
        "image": "oci:" + PROOF.GUEST_LAYOUT,
        "targetImgref": source["target_imgref"],
        **source["storage"],
        "encryption": {"type": "none"},
        "user": {"username": "canary", "groups": ["wheel"]},
        "imageType": "bootc",
        "hostname": "canary",
    }


def device(path, number, *, serial=None, kind="disk", parent=None, mounts=None, uuid=None):
    return {
        "name": path,
        "kname": path,
        "path": path,
        "type": kind,
        "size": PROOF.DISK.TARGET_BYTES,
        "ro": False,
        "serial": serial,
        "maj:min": number,
        "pkname": parent,
        "mountpoints": mounts or [None],
        "fstype": "xfs" if mounts else None,
        "pttype": None,
        "uuid": uuid,
    }


def observed(serial="fork-target-123", *, path="/dev/vda", boot=TARGET_BOOT):
    disk = device(path, "252:0", serial=serial)
    partition = device(
        path + "3", "252:3", kind="part", parent=path, mounts=["/sysroot", "/var"], uuid="aabb-1234"
    )
    disk["children"] = [partition]
    disk["pttype"] = "gpt"
    actual = {
        "target": "/",
        "source": "composefs:/",
        "fstype": "overlay",
        "fsroot": "/",
        "id": 40,
        "parent": 1,
        "maj:min": "0:42",
    }
    backing = {
        "target": "/sysroot",
        "source": path + "3",
        "fstype": "xfs",
        "fsroot": "/",
        "id": 41,
        "parent": 40,
        "maj:min": "252:3",
    }
    source = receipt()
    return {
        "boot_id": boot,
        "account_status": "ok",
        "uid": 1000,
        "account_groups_status": "ok",
        "account_primary_group": "canary",
        "account_groups": ["canary", "wheel"],
        "observer_sha256": OBSERVER_SHA,
        "fork_config_sha256": "d" * 64,
        "lsblk": {"status": "ok", "returncode": 0, "output": {"blockdevices": [disk]}},
        "findmnt": {"status": "ok", "returncode": 0, "output": {"filesystems": [actual, backing]}},
        "kernel_root": {"status": "ok", "kind": "uuid", "value": "aabb-1234"},
        "bootc": {
            "status": "ok",
            "returncode": 0,
            "output": {
                "status": {
                    "booted": {
                        "image": {
                            "imageDigest": source["source_manifest_digest"],
                            "image": {"image": source["target_imgref"], "transport": "registry"},
                        }
                    }
                }
            },
        },
        "identity_verifier": {"status": "ok", "returncode": 0},
    }


def target(value=None, source=None):
    return PROOF.validate_target(
        value or observed(), source or receipt(), "fork-target-123", OBSERVER_SHA, SOURCE_BOOT
    )


@pytest.mark.parametrize("variant,group", [("yellowfin", "wheel"), ("grouper", "sudo")])
def test_admin_group_is_only_for_exact_local_qualification_cells(variant, group):
    assert PROOF.admin_group(f"localhost/fork-qualification/{variant}:gnome-linux-amd64") == group


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/tuna-os/yellowfin:gnome",
        "localhost/fork-qualification/yellowfin:gnome",
        "localhost/fork-qualification/yellowfin:gnome-linux-arm64",
        "localhost/fork-qualification/marlin:gnome-linux-amd64",
        "localhost/fork-qualification/grouper:kde-linux-amd64",
        "localhost/other/grouper:gnome-linux-amd64",
        "localhost/fork-qualification/yellowfin:gnome-linux-amd64\n",
        "",
        None,
    ],
)
def test_admin_group_does_not_admit_stock_other_arch_or_ambiguous_image(image):
    with pytest.raises((ValueError, TypeError)):
        PROOF.admin_group(image)


def test_recipe_checks_exact_native_processor_values_and_returns_nonsecret_fields():
    value = recipe()
    value["user"]["password"] = "temporary-secret"
    result = PROOF.validate_recipe(value, receipt(), "/dev/vdb", "wheel")
    assert result == {
        k: value[k]
        for k in ("disk", "image", "targetImgref", "composeFsBackend", "bootloader", "filesystem")
    }
    assert "temporary-secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "key,value",
    [
        ("disk", "/dev/vda"),
        ("disk", "/dev/disk/by-id/virtio-target"),
        ("image", "containers-storage:localhost/fork-qualification/yellowfin:gnome-linux-amd64"),
        ("image", "oci:/var/tmp/other-source"),
        ("targetImgref", "ghcr.io/tuna-os/yellowfin:gnome"),
        ("composeFsBackend", 0),
        ("composeFsBackend", "false"),
        ("composeFsBackend", True),
        ("bootloader", "systemd"),
        ("filesystem", "ext4"),
        ("imageType", "ostree"),
        ("encryption", {"type": "luks"}),
        ("user", {"username": "root", "groups": ["wheel"]}),
        ("user", {"username": "canary", "groups": ["wheel", "root"]}),
        ("user", {"username": "canary", "groups": "wheel"}),
        ("customMounts", [{"disk": "/dev/vda"}]),
        ("varDisk", "/dev/vda"),
    ],
)
def test_recipe_rejects_changed_storage_source_target_or_privilege(key, value):
    actual = recipe()
    actual[key] = value
    with pytest.raises(ValueError):
        PROOF.validate_recipe(actual, receipt(), "/dev/vdb", "wheel")


@pytest.mark.parametrize(
    "missing",
    [
        "disk",
        "image",
        "targetImgref",
        "composeFsBackend",
        "bootloader",
        "filesystem",
        "user",
        "encryption",
    ],
)
def test_recipe_requires_every_load_bearing_field(missing):
    actual = recipe()
    actual.pop(missing)
    with pytest.raises(ValueError):
        PROOF.validate_recipe(actual, receipt(), "/dev/vdb", "wheel")


def test_root_binding_accepts_real_null_disk_uuid_and_preserves_composefs_root():
    actual = observed()
    before = copy.deepcopy(actual)
    result = PROOF.root_binding(actual, "fork-target-123")
    assert result["partition"] == "/dev/vda3"
    assert result["uuid"] == "aabb-1234"
    assert result["actual_root"]["source"] == "composefs:/"
    assert result["actual_root"]["maj:min"] == "0:42"
    assert result["backing_mounts"][0]["source"] == "/dev/vda3"
    assert actual == before


def test_kernel_uuid_match_is_case_insensitive_but_unique():
    actual = observed()
    actual["kernel_root"]["value"] = "AABB-1234"
    assert PROOF.root_binding(actual, "fork-target-123")["partition"] == "/dev/vda3"
    duplicate = device("/dev/vda4", "252:4", kind="part", parent="/dev/vda", uuid="AABB-1234")
    actual["lsblk"]["output"]["blockdevices"][0]["children"].append(duplicate)
    with pytest.raises(ValueError):
        PROOF.root_binding(actual, "fork-target-123")


def test_block_root_device_token_is_independently_correlated():
    actual = observed()
    actual["kernel_root"] = {"status": "ok", "kind": "device", "value": "/dev/vda3"}
    actual["findmnt"]["output"]["filesystems"] = [
        {
            "target": "/",
            "source": "/dev/vda3",
            "fstype": "xfs",
            "fsroot": "/",
            "id": 40,
            "parent": 1,
            "maj:min": "252:3",
        }
    ]
    actual["lsblk"]["output"]["blockdevices"][0]["children"][0]["mountpoints"] = ["/"]
    assert PROOF.root_binding(actual, "fork-target-123")["actual_root"]["source"] == "/dev/vda3"


@pytest.mark.parametrize(
    "change",
    [
        "wrong_serial",
        "duplicate_serial",
        "unknown_uuid",
        "wrong_disk_uuid",
        "missing_root",
        "duplicate_root",
        "missing_backing",
        "wrong_backing_number",
        "wrong_backing_source",
        "missing_lsblk_mountpoint",
        "failed_lsblk",
        "failed_findmnt",
    ],
)
def test_root_binding_refuses_incomplete_or_contradictory_evidence(change):
    actual = observed()
    disks = actual["lsblk"]["output"]["blockdevices"]
    mounts = actual["findmnt"]["output"]["filesystems"]
    if change in ("wrong_backing_source", "missing_lsblk_mountpoint"):
        # Isolate mount correlation from the separate nullable-UUID regression.
        actual["kernel_root"] = {"status": "ok", "kind": "device", "value": "/dev/vda3"}
    if change == "wrong_serial":
        disks[0]["serial"] = "another-disk"
    elif change == "duplicate_serial":
        disks.append(copy.deepcopy(disks[0]))
    elif change == "unknown_uuid":
        actual["kernel_root"]["value"] = "deaf-beef"
    elif change == "wrong_disk_uuid":
        disks[0]["children"][0]["uuid"] = "deaf-beef"
        other = device("/dev/vdb", "252:16", serial="other-disk")
        other["children"] = [
            device("/dev/vdb3", "252:19", kind="part", parent="/dev/vdb", uuid="aabb-1234")
        ]
        disks.append(other)
    elif change == "missing_root":
        mounts.pop(0)
    elif change == "duplicate_root":
        mounts.append(copy.deepcopy(mounts[0]))
    elif change == "missing_backing":
        mounts.pop(1)
    elif change == "wrong_backing_number":
        mounts[1]["maj:min"] = "252:19"
    elif change == "wrong_backing_source":
        mounts[1]["source"] = "/dev/vdb3"
    elif change == "missing_lsblk_mountpoint":
        disks[0]["children"][0]["mountpoints"] = [None]
    elif change == "failed_lsblk":
        actual["lsblk"]["status"] = "timeout"
    elif change == "failed_findmnt":
        actual["findmnt"]["status"] = "timeout"
    with pytest.raises(ValueError):
        PROOF.root_binding(actual, "fork-target-123")


def test_target_boot_binds_original_platform_manifest_not_source_config_or_harness():
    result = target()
    assert result["installed_manifest_digest"] == receipt()["source_manifest_digest"]
    assert result["installed_manifest_digest"] != receipt()["source_image_id"]
    assert result["tracking_reference"] == receipt()["target_imgref"]
    assert result["boot_id"] == TARGET_BOOT


@pytest.mark.parametrize("digest", ["source_config", "harness_manifest", "missing"])
def test_target_rejects_config_id_or_derived_harness_manifest(digest):
    actual = observed()
    value = {
        "source_config": receipt()["source_image_id"],
        "harness_manifest": "sha256:" + "9" * 64,
        "missing": None,
    }[digest]
    actual["bootc"]["output"]["status"]["booted"]["image"]["imageDigest"] = value
    with pytest.raises(ValueError, match="digest"):
        target(actual)


@pytest.mark.parametrize(
    "change",
    [
        "source_boot",
        "observer",
        "fork_config",
        "bootc",
        "tracking",
        "extra_disk",
        "wrong_disk",
        "identity",
    ],
)
def test_target_requires_new_boot_exact_observer_identity_and_only_target_disk(change):
    actual = observed()
    if change == "source_boot":
        actual["boot_id"] = SOURCE_BOOT
    elif change == "observer":
        actual["observer_sha256"] = "0" * 64
    elif change == "fork_config":
        actual["fork_config_sha256"] = "0" * 64
    elif change == "bootc":
        actual["bootc"]["status"] = "unavailable"
    elif change == "tracking":
        actual["bootc"]["output"]["status"]["booted"]["image"]["image"]["image"] = (
            "ghcr.io/tuna-os/yellowfin:gnome"
        )
    elif change == "extra_disk":
        actual["lsblk"]["output"]["blockdevices"].append(
            device("/dev/vdb", "252:16", serial="source-left-attached")
        )
    elif change == "wrong_disk":
        actual["lsblk"]["output"]["blockdevices"][0]["serial"] = "source"
    elif change == "identity":
        actual["identity_verifier"] = {"status": "command_failed", "returncode": 2}
    with pytest.raises(ValueError):
        target(actual)


def qmp_block(spec):
    return {
        "qdev": spec["qdev"],
        "removable": False,
        "inserted": {
            "file": spec["path"],
            "node-name": spec["node_name"],
            "drv": "qcow2",
            "ro": False,
            "image": {
                "filename": spec["path"],
                "format": "qcow2",
                "virtual-size": PROOF.DISK.TARGET_BYTES,
                "format-specific": {"type": "qcow2", "data": {"corrupt": False}},
            },
        },
    }


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    source_path, target_path = tmp_path / "source.fixture", private / "target.fixture"
    source_path.write_bytes(b"source fixture only")
    target_path.write_bytes(b"target fixture only")
    target_path.chmod(0o600)
    st = target_path.stat()
    source_spec = {
        "path": str(source_path),
        "node_name": "source-node",
        "qdev": "/machine/peripheral/source/virtio-backend",
        "serial": "fork-source-123",
    }
    target_spec = {
        "path": str(target_path),
        "node_name": "target-node",
        "qdev": "/machine/peripheral/target/virtio-backend",
        "serial": "fork-target-123",
    }
    creation = {
        "method": "exclusive-new-file",
        "path": str(target_path),
        "device": st.st_dev,
        "inode": st.st_ino,
    }
    query = {
        "query_block": {"return": [qmp_block(source_spec), qmp_block(target_spec)]},
        "serial_queries": [
            {"path": item["qdev"], "property": "serial", "response": {"return": item["serial"]}}
            for item in (source_spec, target_spec)
        ],
    }
    observation = observed("fork-source-123", boot=SOURCE_BOOT)
    target_disk = device("/dev/vdb", "252:16", serial="fork-target-123")
    observation["lsblk"]["output"]["blockdevices"].append(target_disk)
    facts = {
        "lsblk": copy.deepcopy(observation["lsblk"]["output"]),
        "by_id": {
            "path": "/dev/disk/by-id/virtio-fork-target-123",
            "resolved": "/dev/vdb",
            "returncode": 0,
        },
        "wipefs": {"device": "/dev/vdb", "returncode": 0, "output": {"signatures": []}},
    }
    calls = []

    def guest_call(*args):
        calls.append(args[2])
        return facts

    monkeypatch.setattr(PROOF, "guest_call", guest_call)
    vm = SimpleNamespace(
        source_spec=source_spec, target_spec=target_spec, disk_evidence=lambda: query
    )
    return SimpleNamespace(
        vm=vm,
        creation=creation,
        private=private,
        facts=facts,
        observation=observation,
        query=query,
        calls=calls,
        execute=lambda: PROOF.guarded_disks(vm, creation, {}, private, lambda: observation),
    )


def test_guard_success_retains_real_composefs_source_and_unchanged_fixture_files(guarded):
    before = {
        role: Path(getattr(guarded.vm, role + "_spec")["path"]).read_bytes()
        for role in ("source", "target")
    }
    result = guarded.execute()
    assert result["preflight"] == "passed" and result["target_path"] == "/dev/vdb"
    assert result["source_root"]["actual_root"]["source"] == "composefs:/"
    assert before == {
        role: Path(getattr(guarded.vm, role + "_spec")["path"]).read_bytes()
        for role in ("source", "target")
    }
    assert len(guarded.calls) == 1 and '"wipefs","--no-act"' in guarded.calls[0]
    assert "to-disk" not in guarded.calls[0] and "mkfs" not in guarded.calls[0]


@pytest.mark.parametrize(
    "key,value",
    [
        ("size", PROOF.DISK.TARGET_BYTES - 1),
        ("ro", True),
        ("ro", 0),
        ("children", [{"path": "/dev/vdb1"}]),
        ("fstype", "ext4"),
        ("pttype", "gpt"),
        ("mountpoints", ["/mnt/important"]),
        ("mountpoints", None),
        ("type", "part"),
        ("serial", "fork-source-123"),
        ("path", "/dev/vdc"),
        ("name", "/dev/disk/by-id/virtio-fork-target-123"),
    ],
)
def test_guard_rejects_dirty_nonempty_or_ambiguous_target(guarded, key, value):
    guarded.facts["lsblk"]["blockdevices"][1][key] = value
    with pytest.raises(ValueError):
        guarded.execute()


@pytest.mark.parametrize(
    "change",
    [
        "third_guest_disk",
        "third_qmp_disk",
        "wipefs_signatures",
        "wrong_wipefs_device",
        "failed_wipefs",
        "wrong_byid_name",
        "failed_byid",
        "wrong_resolved",
        "source_size",
        "creation_inode",
    ],
)
def test_guard_rejects_wrong_or_stale_disk_evidence(guarded, change):
    if change in ("wrong_wipefs_device", "failed_wipefs", "wrong_byid_name", "failed_byid"):
        # Use a supported direct root token so this gate is tested independently.
        guarded.observation["kernel_root"] = {
            "status": "ok",
            "kind": "device",
            "value": "/dev/vda3",
        }
    if change == "third_guest_disk":
        guarded.facts["lsblk"]["blockdevices"].append(
            device("/dev/vdc", "252:32", serial="unexpected")
        )
    elif change == "third_qmp_disk":
        guarded.query["query_block"]["return"].append(
            copy.deepcopy(guarded.query["query_block"]["return"][0])
        )
    elif change == "wipefs_signatures":
        guarded.facts["wipefs"]["output"]["signatures"] = [{"type": "gpt"}]
    elif change == "wrong_wipefs_device":
        guarded.facts["wipefs"]["device"] = "/dev/vda"
    elif change == "failed_wipefs":
        guarded.facts["wipefs"]["returncode"] = 1
    elif change == "wrong_byid_name":
        guarded.facts["by_id"]["path"] = "/dev/disk/by-id/virtio-other"
    elif change == "failed_byid":
        guarded.facts["by_id"]["returncode"] = 1
    elif change == "wrong_resolved":
        guarded.facts["by_id"]["resolved"] = "/dev/vda"
    elif change == "source_size":
        guarded.facts["lsblk"]["blockdevices"][0]["size"] -= 1024
    elif change == "creation_inode":
        guarded.creation["inode"] += 1
    with pytest.raises(ValueError):
        guarded.execute()


def test_redaction_removes_known_plaintext_sha512_hash_and_secret_fields_recursively():
    secret = "shortlivedtest123"
    hashed = "$6$salt1234$ABCdef/0123456789.abcdef"
    value = {
        "message": f"prefix {secret} {hashed}",
        "password": secret,
        "nested": [{"passphrase": secret, "recovery_key": "abc", "safe": "kept", "log": hashed}],
        "size": 12,
        "ready": True,
    }
    scrubbed = PROOF.redact(value, [secret])
    assert secret not in json.dumps(scrubbed) and hashed not in json.dumps(scrubbed)
    assert scrubbed["nested"] == [{"safe": "kept", "log": "<redacted-hash>"}]
    assert scrubbed["size"] == 12 and scrubbed["ready"] is True
    assert value["password"] == secret  # Do not modify the caller's live input.


def test_prepare_recipe_only_requests_native_user_fields_and_never_prefills_secrets(monkeypatch):
    programs = []
    monkeypatch.setattr(
        PROOF,
        "guest_call",
        lambda access, private, program: programs.append(program) or {"native_user_step": True},
    )
    PROOF.prepare_guest_recipe({}, Path("/unused"), receipt(), "wheel")
    assert len(programs) == 1
    program = programs[0]
    assert 'recipe["user"]={"groups":[group]}' in program
    assert 'recipe["steps"]["user"]={"template":"user"}' in program
    assert 'nodes["needs_user_creation"]=True' in program
    assert '"password":' not in program and '"username":' not in program
    assert '"sha256:"+hashlib.sha256(original).hexdigest()' in program
    assert '"sha256:"+hashlib.sha256(catalog_original).hexdigest()' in program
    assert "usermod" not in program and "chpasswd" not in program


def test_ui_password_entry_uses_real_qmp_after_independent_focus_and_same_pid(monkeypatch):
    ui_module = PROOF.UI_MODULE
    states = {k: True for k in ("visible", "showing", "enabled", "sensitive")}
    node = {
        "id": 1,
        "parent": 0,
        "pid": 200,
        "role": "password text",
        "name": "Password",
        "states": states,
        "bounds": [100, 100, 200, 40],
    }
    initial = {"schema_version": 1, "nodes": [node]}
    focused = copy.deepcopy(initial)
    focused["nodes"][0]["states"]["focused"] = True
    calls = []
    qmp = SimpleNamespace(
        key=lambda *keys: calls.append(("key", keys)),
        type=lambda value: calls.append(("type", value)),
    )
    ui = ui_module.UI(qmp, None, lambda: focused, None)
    monkeypatch.setattr(ui, "capture", lambda label: (None, (800, 600), [], initial))
    monkeypatch.setattr(ui, "point", lambda point, size: calls.append(("point", point)))
    result = ui.field("Password", "shortlivedtest123", secret=True)
    assert calls == [("point", (200, 120)), ("key", ("ctrl", "a")), ("type", "shortlivedtest123")]
    assert "shortlivedtest123" not in json.dumps(result)
    calls.clear()
    focused["nodes"][0]["pid"] = 201
    with pytest.raises(ValueError, match="another application"):
        ui.field("Password", "shortlivedtest123", secret=True)
    assert all(call[0] != "type" for call in calls)


def test_ui_password_must_never_use_normal_text_role(monkeypatch):
    node = {
        "id": 1,
        "pid": 200,
        "role": "text",
        "name": "Password",
        "states": {k: True for k in ("visible", "showing", "enabled", "sensitive", "focused")},
        "bounds": [100, 100, 200, 40],
    }
    snapshot = {"schema_version": 1, "nodes": [node]}
    ui = PROOF.UI_MODULE.UI(None, None, lambda: snapshot, None)
    monkeypatch.setattr(ui, "capture", lambda label: (None, (800, 600), [], snapshot))
    with pytest.raises(ValueError):
        ui.field("Password", "shortlivedtest123", secret=True)


@pytest.mark.parametrize("booted", [None, {}, {"image": None}])
def test_target_not_yet_booted_is_retryable_validation_failure(booted):
    actual = observed()
    actual["bootc"]["output"]["status"]["booted"] = booted
    with pytest.raises(ValueError):
        target(actual)


def serial_module():
    return PROOF.module("serial_test_helpers", "fork-install-observer.py")


def full_serial_snapshot(seq=0, boot=TARGET_BOOT):
    module = serial_module()
    value = observed(boot=boot)
    value.update(
        {
            "schema": module.SCHEMA,
            "schema_version": module.VERSION,
            "seq": seq,
            "uptime": 100 + seq * 2,
            "uid": 1000,
            "account_status": "ok",
            "sessions": [],
            "sessions_status": "ok",
            "gnome_shell": [],
            "gnome_shell_status": "ok",
            "wallpaper": {},
            "wallpaper_status": "not_running",
            "errors": [],
        }
    )
    value["root_backing"] = module.root_backing(value["lsblk"], value["findmnt"])
    return value


@pytest.fixture
def serial_vm(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(PROOF.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(PROOF.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    module = serial_module()
    vm = SimpleNamespace(
        process=SimpleNamespace(poll=lambda: None),
        observer_path=tmp_path / "observer.log",
        serial_path=tmp_path / "serial.log",
    )
    return SimpleNamespace(vm=vm, module=module, now=now, read=PROOF.serial_observer(vm, module))


def test_serial_reader_requires_new_sequence_and_drops_only_unfinished_tail(serial_vm):
    state = serial_vm
    first = state.module.encode_snapshot(full_serial_snapshot()).decode()
    second = state.module.encode_snapshot(full_serial_snapshot(1)).decode()
    state.vm.observer_path.write_text("kernel noise\n" + first + second[:35])
    assert state.read()["seq"] == 0
    state.vm.observer_path.write_text(first + second)
    assert state.read()["seq"] == 1
    with pytest.raises(TimeoutError):
        state.read()
    assert state.now[0] >= 30


def test_serial_reader_never_ignores_malformed_complete_rows_or_boot_changes(serial_vm):
    state = serial_vm
    first = state.module.encode_snapshot(full_serial_snapshot()).decode()
    state.vm.observer_path.write_text(first)
    assert state.read()["boot_id"] == TARGET_BOOT
    state.vm.observer_path.write_text(first + state.module.PREFIX + "{broken}\n")
    with pytest.raises(ValueError, match="malformed"):
        state.read()
    state.vm.observer_path.write_text(
        first + state.module.encode_snapshot(full_serial_snapshot(1, SOURCE_BOOT)).decode()
    )
    with pytest.raises(ValueError, match="another boot"):
        state.read()


def test_serial_reader_checks_guest_exit_even_when_cached_evidence_exists(serial_vm):
    state = serial_vm
    state.vm.observer_path.write_bytes(state.module.encode_snapshot(full_serial_snapshot()))
    state.vm.process.poll = lambda: 0
    with pytest.raises(ValueError, match="guest exited"):
        state.read()


def test_serial_reader_bounds_console_file_before_reading(serial_vm, monkeypatch):
    state = serial_vm

    class Oversized:
        def exists(self):
            return True

        def stat(self):
            return SimpleNamespace(st_size=64 * 1024 * 1024 + 1)

        def read_text(self, **kwargs):
            raise AssertionError("oversized console must not be read")

    state.vm.observer_path = Oversized()
    with pytest.raises(ValueError, match="exceeds bound"):
        state.read()


def test_progress_collection_exports_only_safe_event_flags(monkeypatch):
    captured = []
    monkeypatch.setattr(
        PROOF,
        "guest_call",
        lambda access, private, code: (
            captured.append(code) or {"complete": False, "error": False, "events": 0, "bytes": 0}
        ),
    )
    PROOF.progress_evidence(
        {}, Path("/unused"), "/var/home/canary/.cache/bootc-installer/fisherman-output.log"
    )
    code = captured[0]
    assert 'result={"complete":False,"error":False,"events":0,"bytes":0}' in code
    assert 'value.get("type")=="complete"' in code and 'value.get("overall_pct")==100' in code
    assert 'if value.get("type")=="error"' in code
    assert "16*1024*1024" in code
    assert 'result["message"]' not in code and 'result["key"]' not in code


@pytest.mark.parametrize(
    "change",
    [
        "wrong_shell",
        "not_focused",
        "plain_text",
        "missing_account",
        "missing_dialog",
        "duplicate",
        "wrong_account_pid",
        "background_account",
        "hidden_account",
        "duplicate_account",
    ],
)
def test_polkit_authentication_rejects_unbound_or_ambiguous_secret_destination(monkeypatch, change):
    rows = [
        {
            "text": text,
            "page_num": 1,
            "block_num": 1,
            "par_num": 1,
            "line_num": line,
            "left": 60,
            "top": 30,
            "width": 50,
            "height": 15,
        }
        for line, text in [(1, "Authentication"), (1, "Required"), (2, "canary")]
    ]
    node = {
        "pid": 200,
        "role": "password text",
        "name": "Password",
        "bounds": [50, 50, 200, 35],
        "states": {key: True for key in ("visible", "showing", "enabled", "sensitive", "focused")},
    }
    account = {
        "pid": 200,
        "role": "label",
        "name": "canary",
        "bounds": [50, 25, 200, 20],
        "states": {"visible": True, "showing": True},
    }
    nodes = [node, account]
    if change == "wrong_shell":
        node["pid"] = 201
    elif change == "not_focused":
        node["states"]["focused"] = False
    elif change == "plain_text":
        node["role"] = "text"
    elif change == "missing_account":
        rows = rows[:2]
    elif change == "missing_dialog":
        rows = rows[2:]
    elif change == "duplicate":
        nodes.append(copy.deepcopy(node))
    elif change == "wrong_account_pid":
        account["pid"] = 201
    elif change == "background_account":
        account["bounds"] = [500, 400, 200, 30]
        rows[-1].update(left=510, top=405)
    elif change == "hidden_account":
        account["states"]["showing"] = False
    elif change == "duplicate_account":
        nodes.append(copy.deepcopy(account))
    typed = []
    qmp = SimpleNamespace(type=typed.append, key=lambda *args: None)
    ui = PROOF.UI_MODULE.UI(qmp, None, None, None)
    monkeypatch.setattr(
        ui, "capture", lambda label: (Path("polkit.png"), (800, 600), rows, {"nodes": nodes})
    )
    with pytest.raises(ValueError):
        ui.authenticate("shortlivedtest123", 200)
    assert typed == []


def test_polkit_authentication_returns_no_plaintext(monkeypatch):
    rows = [
        {
            "text": text,
            "page_num": 1,
            "block_num": 1,
            "par_num": 1,
            "line_num": line,
            "left": 60,
            "top": 30,
            "width": 50,
            "height": 15,
        }
        for line, text in [(1, "Authentication"), (1, "Required"), (2, "canary")]
    ]
    node = {
        "pid": 200,
        "role": "password text",
        "name": "Password",
        "bounds": [50, 50, 200, 35],
        "states": {key: True for key in ("visible", "showing", "enabled", "sensitive", "focused")},
    }
    account = {
        "pid": 200,
        "role": "label",
        "name": "canary",
        "bounds": [50, 25, 200, 20],
        "states": {"visible": True, "showing": True},
    }
    calls = []
    ui = PROOF.UI_MODULE.UI(
        SimpleNamespace(
            type=lambda s: calls.append(("type", s)), key=lambda *k: calls.append(("key", k))
        ),
        None,
        None,
        None,
    )
    monkeypatch.setattr(
        ui,
        "capture",
        lambda label: (Path("polkit.png"), (800, 600), rows, {"nodes": [node, account]}),
    )
    evidence = ui.authenticate("shortlivedtest123", 200)
    assert calls == [("type", "shortlivedtest123"), ("key", ("ret",))]
    assert "shortlivedtest123" not in json.dumps(evidence)


def test_serial_first_frame_has_boot_grace_but_later_frames_still_expire(serial_vm, monkeypatch):
    state = serial_vm

    def advance(delay):
        state.now[0] += delay
        if state.now[0] == 100:
            state.vm.observer_path.write_bytes(state.module.encode_snapshot(full_serial_snapshot()))

    monkeypatch.setattr(PROOF.time, "sleep", advance)
    assert state.read()["seq"] == 0
    assert state.now[0] == 100
    with pytest.raises(TimeoutError):
        state.read()
    assert state.now[0] == 130


@pytest.mark.parametrize("image_exists_rc", [1, 125])
def test_main_cleanup_continues_after_corral_delete_raises(tmp_path, monkeypatch, image_exists_rc):
    import sys

    private = tmp_path / "private"
    private.mkdir()
    output = tmp_path / "output"
    commands, signals = [], []
    source = receipt()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualify-fork-install.py",
            "--image",
            source["target_imgref"],
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--installer-artifact",
            str(tmp_path / "installer.flatpak"),
            "--wallpaper",
            str(tmp_path / "wallpaper.png"),
            "--output",
            str(output),
        ],
    )

    class FixtureImage:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def verify(self):
            return None

    monkeypatch.setitem(sys.modules, "yaml", SimpleNamespace(safe_dump=lambda value: "mock-spec\n"))
    monkeypatch.setitem(
        sys.modules, "PIL", SimpleNamespace(Image=SimpleNamespace(open=lambda path: FixtureImage()))
    )
    monkeypatch.setattr(PROOF.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        PROOF.shutil, "which", lambda name: None if name == "tailscale" else "/mock/" + name
    )
    monkeypatch.setattr(PROOF.tempfile, "mkdtemp", lambda **kwargs: str(private))
    monkeypatch.setattr(PROOF, "module", lambda *args: SimpleNamespace())
    monkeypatch.setattr(PROOF, "digest", lambda path: OBSERVER_SHA)
    monkeypatch.setattr(PROOF, "choice", lambda values: "x")
    monkeypatch.setattr(PROOF, "export_source", lambda *args: source)
    monkeypatch.setattr(
        PROOF,
        "identity",
        lambda ref: {
            "reference": ref,
            "id": source["source_image_id"],
            "digest": source["source_manifest_digest"],
            "repo_tags": [source["target_imgref"]],
        },
    )
    monkeypatch.setattr(PROOF.LOGIN, "make_spec", lambda *args: {})

    def run(args, **kwargs):
        commands.append(args)
        if args[0] == "openssl":
            return "$6$temporary-test-hash"
        if "sha256sum" in args:
            return OBSERVER_SHA + "  /observer.py"
        assert args[:2] in (["podman", "run"], ["podman", "tag"], ["podman", "untag"])
        return ""

    monkeypatch.setattr(PROOF.LOGIN, "run", run)

    def subprocess_run(args, **kwargs):
        commands.append(args)
        if args[:2] == ["corral", "vmtest"]:
            raise OSError("mock VM startup failed xxxxxxxxxxxxxxxxxxxxxxxx")
        assert args[:3] == ["podman", "image", "exists"]
        return SimpleNamespace(returncode=image_exists_rc)

    monkeypatch.setattr(PROOF.subprocess, "run", subprocess_run)

    def delete(*args):
        raise TimeoutError("mock cleanup timeout")

    monkeypatch.setattr(PROOF.LOGIN, "delete_vm", delete)
    monkeypatch.setattr(
        PROOF.signal, "signal", lambda sig, handler: signals.append(handler) or "original-handler"
    )
    assert PROOF.main() == 1
    evidence = json.loads((output / "install-proof.json").read_text())
    assert evidence["cleanup"] == "failed"
    if image_exists_rc == 125:
        assert any("derived image cleanup" in error for error in evidence["cleanup_errors"])
    assert any(args[:2] == ["podman", "untag"] for args in commands)
    assert any(args[:3] == ["podman", "image", "exists"] for args in commands)
    assert private.exists(), "unverified VM cleanup must retain potentially live disk files"
    assert signals[-1] == "original-handler"
    assert "xxxxxxxxxxxxxxxxxxxxxxxx" not in json.dumps(evidence)
    assert "$6$temporary-test-hash" not in json.dumps(evidence)


def completed_report():
    value = dict.fromkeys(PROOF.PASS_PHASES, "passed")
    for phase in ("source", "target"):
        value[phase + "_lifecycle"] = {
            "clean_exit": True,
            "shutdown_event": {"guest": True, "reason": "guest-shutdown"},
        }
    return value


def test_qualification_requires_both_real_guest_shutdowns():
    assert PROOF.qualification_passed(completed_report()) is True


@pytest.mark.parametrize("phase", PROOF.PASS_PHASES)
@pytest.mark.parametrize("status", ["failed", "not-run", "running", True, None])
def test_qualification_requires_every_phase_to_pass(phase, status):
    report = completed_report()
    report[phase] = status
    assert PROOF.qualification_passed(report) is False


@pytest.mark.parametrize("phase", ["source", "target"])
@pytest.mark.parametrize(
    "lifecycle",
    [
        {},
        {"clean_exit": True},
        {"clean_exit": False, "shutdown_event": {"guest": True, "reason": "guest-shutdown"}},
        {"clean_exit": 1, "shutdown_event": {"guest": True, "reason": "guest-shutdown"}},
        {"clean_exit": True, "shutdown_event": {"guest": False, "reason": "host-qmp-quit"}},
        {"clean_exit": True, "shutdown_event": {"guest": 1, "reason": "guest-shutdown"}},
        {"clean_exit": True, "shutdown_event": {"guest": True, "reason": "guest-reset"}},
    ],
)
def test_forced_or_unverified_cleanup_cannot_earn_passed_qualification(phase, lifecycle):
    report = completed_report()
    report[phase + "_lifecycle"] = lifecycle
    assert PROOF.qualification_passed(report) is False


def test_shutdown_failure_cannot_be_hidden_by_otherwise_passed_phase_flags():
    report = completed_report()
    report["error"] = "target shutdown failed"
    assert PROOF.qualification_passed(report) is False


@pytest.mark.parametrize(
    "change",
    [
        {"account_groups_status": "unavailable"},
        {"account_groups_status": "absent"},
        {"account_primary_group": "wheel"},
        {"account_groups": ["canary"]},
        {"account_groups": ["canary", "docker", "wheel"]},
        {"account_groups": ["canary", "incus-admin", "wheel"]},
        {"account_groups": ["canary", "libvirt", "wheel"]},
        {"account_status": "absent", "uid": None},
    ],
)
def test_target_requires_native_exact_family_groups(change):
    value = observed()
    value.update(change)
    with pytest.raises(ValueError):
        target(value)


def test_grouper_native_account_uses_sudo_without_yellowfin_defaults():
    source = receipt()
    source["target_imgref"] = source["target_imgref"].replace("yellowfin", "grouper")
    value = observed()
    value["bootc"]["output"]["status"]["booted"]["image"]["image"]["image"] = source[
        "target_imgref"
    ]
    value["account_groups"] = ["canary", "sudo"]
    target(value, source)
    for extra in ("wheel", "docker", "incus-admin", "libvirt", "dialout"):
        value["account_groups"] = sorted(["canary", "sudo", extra])
        with pytest.raises(ValueError):
            target(value, source)


def test_functional_proof_does_not_claim_complete_installer_branding():
    text = (Path(__file__).resolve().parents[1] / "scripts/qualify-fork-install.py").read_text()
    assert '"production_installer_qualified": False' in text
    assert 'report["installer_done_branding"]' in text
    assert '"Harbor Canary is installed"' in text


@pytest.mark.parametrize("prefix", ["", "sha256:"])
def test_inspected_image_id_is_canonical_and_matches_export(prefix, monkeypatch):
    source = receipt()
    raw_id = prefix + "b" * 64
    command = []

    def run(args, **kwargs):
        command.append((args, kwargs))
        return json.dumps(
            [
                {
                    "Id": raw_id,
                    "Digest": source["source_manifest_digest"],
                    "RepoTags": [source["target_imgref"]],
                }
            ]
        )

    monkeypatch.setattr(PROOF.LOGIN, "run", run)
    observed = PROOF.identity(source["target_imgref"])
    assert observed["id"] == source["source_image_id"]
    assert observed["digest"] != observed["id"], "manifest digest is not the config ID"
    PROOF.validate_source_binding(source, observed, source["target_imgref"])
    assert command == [(["podman", "image", "inspect", source["target_imgref"]], {"timeout": 60})]


@pytest.mark.parametrize(
    "bad_id",
    [
        None,
        True,
        123,
        {},
        [],
        "",
        "sha256:",
        "b" * 63,
        "b" * 65,
        "sha256:" + "g" * 64,
        "sha256:" + "B" * 64,
        "B" * 64,
        "sha512:" + "b" * 64,
        "sha256:sha256:" + "b" * 64,
        " " + "b" * 64,
        "b" * 64 + "\n",
        "localhost/repo@sha256:" + "b" * 64,
    ],
)
def test_identity_rejects_malformed_or_ambiguous_config_ids(bad_id, monkeypatch):
    monkeypatch.setattr(PROOF.LOGIN, "run", lambda *a, **kw: json.dumps([{"Id": bad_id}]))
    with pytest.raises(ValueError, match="invalid SHA-256 config ID"):
        PROOF.identity(receipt()["target_imgref"])


@pytest.mark.parametrize(
    "data", [[], [{}, {}], [None], ["not-an-object"], {}, [{"Digest": "sha256:" + "c" * 64}]]
)
def test_identity_rejects_missing_or_nonunique_inspection(data, monkeypatch):
    monkeypatch.setattr(PROOF.LOGIN, "run", lambda *a, **kw: json.dumps(data))
    with pytest.raises(ValueError):
        PROOF.identity(receipt()["target_imgref"])


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "digest",
        "config_digest",
        "manifest_digest",
        "source_image_id",
        "source_manifest_digest",
        "target_imgref",
        "reference",
        "preserved_digest",
    ],
)
def test_normalization_never_hides_different_source_or_manifest(field):
    source = receipt()
    inspected = {
        "reference": source["target_imgref"],
        "id": source["source_image_id"],
        "digest": source["source_manifest_digest"],
    }
    other = "sha256:" + "9" * 64
    if field in ("id", "digest", "reference"):
        inspected[field] = other
    elif field in ("config_digest", "manifest_digest"):
        source["verified_oci"][field] = other
    else:
        source[field] = False if field == "preserved_digest" else other
    with pytest.raises(ValueError):
        PROOF.validate_source_binding(source, inspected, receipt()["target_imgref"])


@pytest.mark.parametrize("digest", [None, "", "c" * 64, "sha512:" + "c" * 64, "sha256:" + "C" * 64])
def test_binding_requires_exact_inspected_platform_manifest_digest(digest):
    source = receipt()
    inspected = {
        "reference": source["target_imgref"],
        "id": source["source_image_id"],
        "digest": digest,
    }
    with pytest.raises(ValueError, match="platform manifest digest"):
        PROOF.validate_source_binding(source, inspected, source["target_imgref"])


def catalog(nodes=None):
    return {
        "default_image": receipt()["target_imgref"],
        "images": nodes
        if nodes is not None
        else [{"name": " Harbor Canary ", "imgref": receipt()["target_imgref"]}],
    }


def test_done_name_uses_exact_catalog_name_not_slug():
    original = catalog()
    assert PROOF.selected_catalog_name(original, receipt()["target_imgref"]) == "Harbor Canary"
    assert original["images"][0]["name"] == " Harbor Canary "


def test_done_name_inherits_only_nearest_registry_owner_for_tag_leaf():
    ref = receipt()["target_imgref"]
    registry, tag = ref.rsplit(":", 1)
    tree = catalog(
        [
            {
                "name": "Outer Name",
                "registry": "localhost/other",
                "children": [
                    {
                        "name": "Harbor Canary",
                        "registry": registry,
                        "children": [
                            {
                                "name": "Desktop Group",
                                "children": [{"name": "Stable channel", "tag": tag}],
                            }
                        ],
                    }
                ],
            }
        ]
    )
    assert PROOF.selected_catalog_name(tree, ref) == "Harbor Canary"


def test_direct_reference_name_does_not_inherit_registry_or_group_name():
    ref = receipt()["target_imgref"]
    tree = catalog(
        [
            {
                "name": "Wrong Group",
                "registry": "localhost/unrelated",
                "children": [{"name": "Harbor Canary", "imgref": ref, "tag": "ignored"}],
            }
        ]
    )
    assert PROOF.selected_catalog_name(tree, ref) == "Harbor Canary"


def test_done_name_resolves_native_one_pass_catalog_aliases():
    ref = receipt()["target_imgref"]
    tree = catalog([{"name": "@product", "imgref": "@reference"}])
    tree.update(default_image="@reference", aliases={"product": "Harbor Canary", "reference": ref})
    assert PROOF.selected_catalog_name(tree, ref) == "Harbor Canary"


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "wrong_default",
        "blank_name",
        "nonstr_name",
        "wrong_ref",
        "wrong_tree",
        "wrong_node",
        "unknown_alias",
        "chained_alias",
    ],
)
def test_done_name_rejects_guessed_or_ambiguous_catalog_identity(change):
    ref = receipt()["target_imgref"]
    tree = catalog()
    if change == "missing":
        tree["images"] = []
    elif change == "duplicate":
        tree["images"] *= 2
    elif change == "wrong_default":
        tree["default_image"] = "localhost/other:latest"
    elif change == "blank_name":
        tree["images"][0]["name"] = " "
    elif change == "nonstr_name":
        tree["images"][0]["name"] = 123
    elif change == "wrong_ref":
        tree["images"][0]["imgref"] = "localhost/other:latest"
    elif change == "wrong_tree":
        tree["images"] = {}
    elif change == "wrong_node":
        tree["images"] = [False]
    elif change == "unknown_alias":
        tree["images"][0]["name"] = "@missing"
    elif change == "chained_alias":
        tree["images"][0]["name"] = "@product"
        tree["aliases"] = {"product": "@next", "next": "Harbor Canary"}
    with pytest.raises(ValueError):
        PROOF.selected_catalog_name(tree, ref)


def test_failed_source_binding_retains_both_provenance_observations(tmp_path, monkeypatch):
    import sys

    from PIL import Image

    original = receipt()
    exported = copy.deepcopy(original)
    exported["source_image_id"] = "sha256:" + "9" * 64
    inspected = {
        "reference": original["target_imgref"],
        "id": original["source_image_id"],
        "digest": original["source_manifest_digest"],
        "repo_tags": [original["target_imgref"]],
    }
    private = tmp_path / "private"
    private.mkdir()
    wallpaper = tmp_path / "wallpaper.png"
    Image.new("RGB", (4, 4), "black").save(wallpaper)
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qualify-fork-install.py",
            "--image",
            original["target_imgref"],
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--installer-artifact",
            str(tmp_path / "installer.zip"),
            "--wallpaper",
            str(wallpaper),
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(PROOF.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        PROOF.shutil, "which", lambda name: None if name == "tailscale" else "/mock/" + name
    )
    monkeypatch.setattr(PROOF.tempfile, "mkdtemp", lambda **kwargs: str(private))
    monkeypatch.setattr(PROOF, "module", lambda *args: SimpleNamespace())
    monkeypatch.setattr(PROOF, "identity", lambda image: inspected)
    monkeypatch.setattr(PROOF, "export_source", lambda *args: exported)
    monkeypatch.setattr(PROOF, "digest", lambda path: OBSERVER_SHA)

    def run(args, **kwargs):
        assert args[:2] == ["podman", "run"], "binding failure must precede tag/VM setup"
        assert original["source_image_id"] in args, "runtime uses canonical config ID"
        return OBSERVER_SHA + "  observer.py" if "sha256sum" in args else ""

    monkeypatch.setattr(PROOF.LOGIN, "run", run)
    assert PROOF.main() == 1
    value = json.loads((output / "install-proof.json").read_text())
    assert value["source_image"] == inspected
    assert value["source_receipt"] == exported
    assert value["error"] == "export is not the same finalized original image"
    assert value["status"] == "failed" and value["cleanup"] == "passed"
    assert "corral_boot" not in value and "test_password" not in value
    assert not private.exists()


def login_observation(*, active=False, missing_sessions=False):
    value = {
        "boot_id": SOURCE_BOOT,
        "uptime": 110.0 if active else 100.0,
        "uid": 1000,
        "sessions": [],
        "sessions_status": "empty" if missing_sessions else "ok",
        "gnome_shell": [{"pid": 200, "start_ticks": "10500"}] if active else [],
        "gnome_shell_status": "ok",
    }
    if active and not missing_sessions:
        value["sessions"] = [
            dict(
                zip(
                    PROOF.OBSERVER.SESSION_KEYS,
                    (
                        "3",
                        "1000",
                        "canary",
                        "no",
                        "wayland",
                        "user",
                        "yes",
                        "active",
                        "gdm-password",
                        "GNOME",
                        "seat0",
                        "200",
                        "no",
                        "105000000",
                    ),
                    strict=True,
                )
            )
        ]
    return value


@pytest.fixture
def typed_login_case(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(PROOF.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(PROOF.time, "sleep", lambda _: clock.__setitem__(0, clock[0] + 240))
    monkeypatch.setattr(PROOF.LOGIN, "words", lambda _: [])
    monkeypatch.setattr(PROOF.LOGIN, "password_prompt", lambda *a: {"verified": True})
    screens, events = [], []

    def screenshot(name):
        screens.append(name)
        (tmp_path / name).write_bytes(b"fixture pixels")
        return tmp_path / name

    qmp = SimpleNamespace(
        type=lambda text: events.append(("type", text)), key=lambda key: events.append(("key", key))
    )
    return SimpleNamespace(
        clock=clock,
        screens=screens,
        events=events,
        screenshot=screenshot,
        qmp=qmp,
        out=tmp_path,
        password="ephemeral-fixture-secret",
    )


def invoke_typed_login(case, observe):
    return PROOF.typed_login(
        case.qmp, case.screenshot, observe, case.out, case.out, case.password, "cold-source"
    )


def test_typed_login_timeout_keeps_bounded_facts_and_final_frame(typed_login_case):
    case = typed_login_case
    before = login_observation()
    last = login_observation(active=True, missing_sessions=True)
    # Extra command/credential material must never enter failure diagnostics.
    before["untrusted"] = last["untrusted"] = case.password
    values = iter([before, last])
    with pytest.raises(ValueError, match="native gdm-password session"):
        invoke_typed_login(case, lambda: next(values))
    text = (case.out / "cold-source-login.json").read_text()
    report = json.loads(text)
    assert report["status"] == "failed"
    assert report["stage"] == "authenticated_session"
    assert report["before"] == PROOF.login_diagnostic(before)
    assert report["last"] == PROOF.login_diagnostic(last)
    assert report["last"]["sessions_status"] == "empty"
    assert report["last"]["gnome_shell"]
    assert case.screens[-1] == report["screenshot"] == "cold-source-login-failed.png"
    assert case.password not in text and "untrusted" not in text
    assert len(text) < 65536
    assert case.events == [("type", case.password), ("key", "ret")]


def test_typed_login_still_requires_native_password_session(typed_login_case):
    case = typed_login_case
    before, after = login_observation(), login_observation(active=True)
    values = iter([before, after])
    assert invoke_typed_login(case, lambda: next(values)) == (before, after, after["sessions"][0])
    report = json.loads((case.out / "cold-source-login.json").read_text())
    assert report["status"] == "passed" and report["session"]["Service"] == "gdm-password"
    assert "cold-source-login-failed.png" not in case.screens


@pytest.mark.parametrize(
    "change",
    [
        {"Service": "gdm-autologin"},
        {"Remote": "yes"},
        {"LockedHint": "yes"},
        {"Class": "greeter"},
        {"Type": "tty"},
        {"Name": "root"},
        {"Active": "no"},
        {"TimestampMonotonic": "99000000"},
    ],
)
def test_failed_login_diagnostics_never_relax_authentication(typed_login_case, change):
    case = typed_login_case
    after = login_observation(active=True)
    after["sessions"][0].update(change)
    values = iter([login_observation(), after])
    with pytest.raises(ValueError):
        invoke_typed_login(case, lambda: next(values))
    report = json.loads((case.out / "cold-source-login.json").read_text())
    assert report["status"] == "failed" and report["last"] == after


def test_typed_login_preexisting_session_fails_without_password_input(typed_login_case):
    case = typed_login_case
    with pytest.raises(ValueError, match="existed before password"):
        invoke_typed_login(case, lambda: login_observation(active=True))
    report = json.loads((case.out / "cold-source-login.json").read_text())
    assert report["status"] == "failed" and report["stage"] == "before_password"
    assert report["before"]["gnome_shell"] and report["last"] is None
    assert case.events == []


def test_observer_failure_preserves_last_validated_frame_without_exception_text(
    typed_login_case, monkeypatch
):
    case = typed_login_case
    monkeypatch.setattr(PROOF.time, "sleep", lambda _: case.clock.__setitem__(0, case.clock[0] + 1))
    values = iter([login_observation(), login_observation(active=True, missing_sessions=True)])

    def observe():
        try:
            return next(values)
        except StopIteration:
            raise TimeoutError(case.password)

    with pytest.raises(TimeoutError):
        invoke_typed_login(case, observe)
    text = (case.out / "cold-source-login.json").read_text()
    assert json.loads(text)["last"]["gnome_shell"]
    assert case.password not in text and "TimeoutError" not in text


def test_invalid_observer_data_is_not_published(typed_login_case):
    case = typed_login_case
    malformed = login_observation(active=True)
    malformed["sessions"][0]["credential"] = case.password
    values = iter([login_observation(), malformed])
    with pytest.raises(ValueError, match="invalid login session properties"):
        invoke_typed_login(case, lambda: next(values))
    text = (case.out / "cold-source-login.json").read_text()
    assert json.loads(text)["last"] is None and case.password not in text


def test_final_screenshot_failure_cannot_hide_login_failure(typed_login_case):
    case = typed_login_case
    screen = case.screenshot

    def screenshot(name):
        if name.endswith("-failed.png"):
            raise OSError(case.password)
        return screen(name)

    case.screenshot = screenshot
    values = iter([login_observation(), login_observation(active=True, missing_sessions=True)])
    with pytest.raises(ValueError, match="native gdm-password session"):
        invoke_typed_login(case, lambda: next(values))
    text = (case.out / "cold-source-login.json").read_text()
    assert json.loads(text)["screenshot_status"] == "unavailable" and case.password not in text


@pytest.mark.parametrize(
    "change",
    [
        {"boot_id": "bad"},
        {"uptime": float("nan")},
        {"uptime": True},
        {"uptime": -1},
        {"uid": 0},
        {"uid": True},
        {"sessions": [{}]},
        {"sessions": "3"},
        {"sessions": [dict.fromkeys(PROOF.OBSERVER.SESSION_KEYS, "x" * 257)]},
        {"gnome_shell": [{"pid": 1, "start_ticks": "1" * 33}]},
        {"gnome_shell": [{"pid": True, "start_ticks": "1"}]},
        {"gnome_shell_status": "invalid"},
        {"sessions_status": ["ok"]},
    ],
)
def test_login_diagnostic_rejects_malformed_or_unbounded_data(change):
    value = login_observation()
    value.update(change)
    with pytest.raises(ValueError):
        PROOF.login_diagnostic(value)


def test_dedicated_reader_never_uses_console_only_evidence(serial_vm):
    state = serial_vm
    state.vm.serial_path.write_bytes(state.module.encode_snapshot(full_serial_snapshot()))
    with pytest.raises(TimeoutError, match="private-port"):
        state.read()
    assert state.now[0] == 480


def test_damaged_console_does_not_poison_private_observer(serial_vm):
    state = serial_vm
    state.vm.serial_path.write_text(state.module.PREFIX + '{"damaged":TUNAOS_BASE_CONTRACT_OK\n')
    state.vm.observer_path.write_bytes(state.module.encode_snapshot(full_serial_snapshot()))
    assert state.read()["seq"] == 0
    # The damaged private stream remains fatal even when console data is valid.
    state.vm.serial_path.write_bytes(state.module.encode_snapshot(full_serial_snapshot(1)))
    state.vm.observer_path.write_text(state.module.PREFIX + "{damaged}\n")
    with pytest.raises(ValueError, match="malformed"):
        state.read()


def test_final_evidence_uses_only_dedicated_private_channel():
    source = (ROOT / "scripts/qualify-fork-install.py").read_text()
    assert "vm.serial_path" not in source
    assert "parse_lines(bounded_serial_text(vm.observer_path))" in "".join(source.split())


def test_concurrent_console_writes_cannot_corrupt_private_observer(serial_vm):
    state = serial_vm
    started, stop = threading.Event(), threading.Event()
    writes = []

    def console_writer():
        with state.vm.serial_path.open("w") as stream:
            while not stop.is_set() and len(writes) < 2000:
                stream.write(
                    state.module.PREFIX + '{"interrupted":/dev/vTUNAOS_BASE_CONTRACT_OK\nda3\n'
                )
                stream.flush()
                writes.append(1)
                started.set()

    writer = threading.Thread(target=console_writer, daemon=True)
    writer.start()
    try:
        assert started.wait(3)
        with state.vm.observer_path.open("w") as stream:
            for seq in range(10):
                stream.write(state.module.encode_snapshot(full_serial_snapshot(seq)).decode())
                stream.flush()
                assert state.read()["seq"] == seq
        assert writes
    finally:
        stop.set()
        writer.join(timeout=3)
    assert not writer.is_alive()


def test_accessibility_failure_is_retained_before_navigation(monkeypatch, tmp_path):
    error = {'exception_type': 'ValueError', 'message': 'accessibility label relation has an unresolved target', 'traceback': [{'file': '<fork-accessibility>', 'line': 84}]}
    monkeypatch.setattr(PROOF, 'guest_call', lambda *args: {'schema_version': 1, 'probe_error': error})
    report = {}
    with pytest.raises(ValueError, match='native accessibility probe failed: ValueError'):
        PROOF.accessibility({}, tmp_path, [42], report)
    assert report['native_ui_probe_error'] == error
