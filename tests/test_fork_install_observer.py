"""Serial evidence is read-only, bounded, attributable, and never fabricated."""

import copy
import importlib.util
import json
import os
import shutil
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fork_install_observer", ROOT / "scripts/fork-install-observer.py"
)
OBSERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OBSERVER)
LOGIN_SPEC = importlib.util.spec_from_file_location(
    "fork_login_compat", ROOT / "scripts/qualify-fork-login.py"
)
LOGIN = importlib.util.module_from_spec(LOGIN_SPEC)
LOGIN_SPEC.loader.exec_module(LOGIN)
BOOT_ID = "01234567-89ab-cdef-0123-456789abcdef"


def block_fixture():
    part = {
        "name": "/dev/vda3",
        "kname": "/dev/vda3",
        "path": "/dev/vda3",
        "type": "part",
        "size": 63000000000,
        "ro": False,
        "serial": None,
        "maj:min": "252:3",
        "pkname": "/dev/vda",
        "mountpoints": ["/sysroot", "/var"],
        "fstype": "xfs",
        "pttype": None,
        "uuid": "aabb-1234",
    }
    disk = {
        "name": "/dev/vda",
        "kname": "/dev/vda",
        "path": "/dev/vda",
        "type": "disk",
        "size": 64000000000,
        "ro": False,
        "serial": "source",
        "maj:min": "252:0",
        "pkname": None,
        "mountpoints": [None],
        "fstype": None,
        "pttype": "gpt",
        "uuid": None,
        "children": [part],
    }
    return {"blockdevices": [disk]}


def mount_fixture():
    return {
        "filesystems": [
            {
                "target": "/",
                "source": "composefs:/",
                "fstype": "overlay",
                "fsroot": "/",
                "id": 40,
                "parent": 1,
                "maj:min": "0:42",
                "children": [
                    {
                        "target": "/sysroot",
                        "source": "/dev/vda3",
                        "fstype": "xfs",
                        "fsroot": "/",
                        "id": 41,
                        "parent": 40,
                        "maj:min": "252:3",
                    },
                    {
                        "target": "/var",
                        "source": "/dev/vda3[/ostree/deploy/var]",
                        "fstype": "xfs",
                        "fsroot": "/ostree/deploy/var",
                        "id": 42,
                        "parent": 40,
                        "maj:min": "252:3",
                    },
                ],
            }
        ]
    }


def snapshot(seq=0):
    blocks = OBSERVER.result("ok", block_fixture(), 0)
    mounts = OBSERVER.result("ok", mount_fixture(), 0)
    return {
        "schema": OBSERVER.SCHEMA,
        "schema_version": OBSERVER.VERSION,
        "seq": seq,
        "observer_sha256": "a" * 64,
        "fork_config_sha256": "b" * 64,
        "boot_id": BOOT_ID,
        "uptime": 100.0 + 2 * seq,
        "uid": None,
        "account_status": "absent",
        "account_groups": [],
        "account_primary_group": None,
        "account_groups_status": "absent",
        "sessions": [],
        "sessions_status": "ok",
        "gnome_shell": [],
        "gnome_shell_status": "absent",
        "wallpaper": {},
        "wallpaper_status": "not_running",
        "bootc": OBSERVER.result(
            "ok", {"status": {"booted": {"image": {"image": "localhost/canary:gnome"}}}}, 0
        ),
        "lsblk": blocks,
        "findmnt": mounts,
        "root_backing": OBSERVER.root_backing(blocks, mounts),
        "kernel_root": {"status": "ok", "kind": "uuid", "value": "aabb-1234"},
        "identity_verifier": {"status": "ok", "returncode": 0},
        "errors": [],
    }


def active_session():
    row = dict.fromkeys(OBSERVER.SESSION_KEYS, "")
    row.update(
        {
            "Id": "3",
            "User": "1000",
            "Name": "canary",
            "Remote": "no",
            "Type": "wayland",
            "Class": "user",
            "Active": "yes",
            "State": "active",
            "Service": "gdm-password",
            "Desktop": "GNOME",
            "Seat": "seat0",
            "Leader": "200",
            "LockedHint": "no",
            "TimestampMonotonic": "105000000",
        }
    )
    return row


def serialized(value):
    return OBSERVER.encode_snapshot(value).decode("ascii")


def test_login_schema_preserves_existing_password_session_validator():
    before = snapshot()
    after = snapshot(4)
    after.update(
        {
            "uid": 1000,
            "account_status": "ok",
            "account_groups": ["canary", "wheel"],
            "account_primary_group": "canary",
            "account_groups_status": "ok",
            "sessions": [active_session()],
            "gnome_shell": [{"pid": 200, "start_ticks": "10400"}],
            "gnome_shell_status": "ok",
            "wallpaper": {
                "picture-uri": "'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'",
                "picture-uri-dark": "'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'",
            },
            "wallpaper_status": "ok",
        }
    )
    OBSERVER.validate_snapshot(before)
    OBSERVER.validate_snapshot(after)
    assert LOGIN.validate_login(before, after)["Service"] == "gdm-password"


def test_serial_noise_ignored_but_tagged_rows_never_skipped():
    text = "kernel noise\r\n" + serialized(snapshot()) + "[serial] " + serialized(snapshot(1))
    assert [v["seq"] for v in OBSERVER.parse_lines(text)] == [0, 1]
    assert OBSERVER.latest(text)["seq"] == 1
    for broken in (OBSERVER.PREFIX + "{\n", OBSERVER.PREFIX + "null\n", OBSERVER.PREFIX + "{}\n"):
        with pytest.raises(ValueError, match="malformed"):
            OBSERVER.latest(text + broken)


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": "hidden output"},
        {"schema_version": True},
        {"schema_version": 1},
        {"seq": True},
        {"seq": -1},
        {"uid": 0},
        {"uid": True},
        {"boot_id": "not-a-boot-id"},
        {"uptime": float("nan")},
        {"uptime": -1},
        {"observer_sha256": None},
        {"fork_config_sha256": "sha256:" + "b" * 64},
        {"sessions": [{}]},
        {"sessions_status": "passed"},
        {"wallpaper": {"secret": "bad"}},
        {"account_status": "ok"},
        {"gnome_shell": [{"pid": 200, "start_ticks": "10400"}]},
        {"bootc": {"status": "ok", "returncode": 0, "output": {}}},
        {"bootc": {"status": "timeout", "returncode": None, "output": "secret stderr"}},
        {"kernel_root": {"status": "ok", "kind": "device", "value": "/dev/../etc/shadow"}},
        {"kernel_root": {"status": "unsupported", "kind": None, "value": "secret"}},
    ],
)
def test_malformed_evidence_rejected(change):
    value = snapshot()
    value.update(change)
    with pytest.raises(ValueError):
        OBSERVER.validate_snapshot(value)


def test_duplicate_keys_nonfinite_and_oversized_tagged_lines_rejected():
    valid = serialized(snapshot())
    for malformed in (
        valid.replace('"seq":0', '"seq":0,"seq":1'),
        valid.replace('"uptime":100.0', '"uptime":NaN'),
        OBSERVER.PREFIX + " " * OBSERVER.MAX_ROW + "{}\n",
    ):
        with pytest.raises(ValueError):
            OBSERVER.parse_lines(malformed)


def test_latest_refuses_old_boot_sequence_and_no_evidence():
    with pytest.raises(ValueError, match="no observer"):
        OBSERVER.latest("kernel only")
    with pytest.raises(ValueError, match="another boot"):
        OBSERVER.latest(serialized(snapshot()), boot_id="11111111-1111-1111-1111-111111111111")
    with pytest.raises(ValueError, match="fresh"):
        OBSERVER.latest(serialized(snapshot()), after_seq=0)
    assert OBSERVER.latest(serialized(snapshot(1)), after_seq=0)["seq"] == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("seq", 0),
        ("uptime", 99),
        ("observer_sha256", "c" * 64),
        ("fork_config_sha256", "c" * 64),
        ("identity_verifier", {"status": "timeout", "returncode": None}),
    ],
)
def test_sequence_and_attribution_must_not_regress(key, value):
    later = snapshot(1)
    later[key] = value
    with pytest.raises(ValueError, match="regressed"):
        OBSERVER.parse_lines(serialized(snapshot()) + serialized(later))


def test_new_boot_can_restart_sequence_but_latest_cannot_reuse_previous_boot():
    later = snapshot()
    later["boot_id"] = "11111111-1111-1111-1111-111111111111"
    text = serialized(snapshot(20)) + serialized(later)
    assert OBSERVER.latest(text)["boot_id"] == later["boot_id"]
    with pytest.raises(ValueError, match="another boot"):
        OBSERVER.latest(text, boot_id=BOOT_ID)


def test_composefs_is_not_replaced_by_sysroot_or_var():
    value = snapshot()
    backing = value["root_backing"]
    assert backing["status"] == "composefs_candidates"
    assert backing["root"]["source"] == "composefs:/"
    assert backing["root"]["maj:min"] == "0:42"
    assert [item["mount"]["target"] for item in backing["block_mounts"]] == ["/sysroot", "/var"]
    assert backing["block_mounts"][1]["mount"]["source"] == "/dev/vda3[/ostree/deploy/var]"
    assert backing["block_mounts"][0]["ancestry"][0]["serial"] == "source"
    assert value["lsblk"]["output"]["blockdevices"][0]["children"][0]["uuid"] == "aabb-1234"


def test_block_root_needs_observed_mount_and_device_correlation():
    value = snapshot()
    root = value["findmnt"]["output"]["filesystems"][0]
    root.update({"source": "/dev/vda3", "fstype": "xfs", "maj:min": "252:3"})
    part = value["lsblk"]["output"]["blockdevices"][0]["children"][0]
    assert OBSERVER.root_backing(value["lsblk"], value["findmnt"])["status"] == "unresolved"
    part["mountpoints"].append("/")
    assert OBSERVER.root_backing(value["lsblk"], value["findmnt"])["status"] == "block_root"
    part["path"] = "/dev/vdb3"
    assert OBSERVER.root_backing(value["lsblk"], value["findmnt"])["status"] == "unresolved"


def test_ambiguous_device_number_or_root_is_not_backing_evidence():
    value = snapshot()
    value["lsblk"]["output"]["blockdevices"].append(
        copy.deepcopy(value["lsblk"]["output"]["blockdevices"][0])
    )
    assert OBSERVER.root_backing(value["lsblk"], value["findmnt"])["status"] == "invalid_data"
    value = snapshot()
    value["findmnt"]["output"]["filesystems"].append(
        copy.deepcopy(value["findmnt"]["output"]["filesystems"][0])
    )
    assert OBSERVER.root_backing(value["lsblk"], value["findmnt"])["status"] == "invalid_data"


@pytest.mark.parametrize(
    "line,expected",
    [
        (
            "quiet root=UUID=aabb-1234 password=never-emit-me",
            {"status": "ok", "kind": "uuid", "value": "aabb-1234"},
        ),
        ("root=/dev/vda3", {"status": "ok", "kind": "device", "value": "/dev/vda3"}),
        ("root=/dev/nvme0n1p3", {"status": "ok", "kind": "device", "value": "/dev/nvme0n1p3"}),
        ("root=UUID=abc root=/dev/vda3", {"status": "ambiguous", "kind": None, "value": None}),
        ("root=UUID=abc root=UUID=abc", {"status": "ambiguous", "kind": None, "value": None}),
        ("root=/dev/mapper/secret", {"status": "unsupported", "kind": None, "value": None}),
        ("root=UUID=secret", {"status": "unsupported", "kind": None, "value": None}),
        ("root=/dev/../../etc/shadow", {"status": "unsupported", "kind": None, "value": None}),
        ("quiet secret=do-not-emit", {"status": "missing", "kind": None, "value": None}),
    ],
)
def test_only_safe_root_token_is_exposed(monkeypatch, line, expected):
    monkeypatch.setattr(OBSERVER, "read_text", lambda *args: line)
    assert OBSERVER.kernel_root() == expected


def test_oversize_row_becomes_explicit_unusable_marker():
    value = snapshot()
    value["bootc"]["output"]["padding"] = "x" * 100000
    encoded = OBSERVER.encode_snapshot(value)
    assert len(encoded) <= OBSERVER.MAX_ROW
    small = OBSERVER.parse_lines(encoded.decode())[0]
    assert small["bootc"]["status"] == "output_limit"
    assert small["sessions_status"] == "output_limit"
    with pytest.raises(ValueError, match="collection errors"):
        OBSERVER.latest(encoded.decode())


@pytest.mark.parametrize(
    "output", ["", "{}", "[]", "null", '{"status":{}}', '{"status":{"booted":null},"x":NaN}']
)
def test_bootc_empty_or_invalid_output_is_not_success(monkeypatch, output):
    monkeypatch.setattr(
        OBSERVER, "command", lambda *args, **kwargs: OBSERVER.result("ok", output, 0)
    )
    assert OBSERVER.json_command(["bootc", "status", "--json"], kind="bootc")["status"] != "ok"


def test_bootc_status_is_preserved_without_projection(monkeypatch):
    payload = {
        "apiVersion": "org.containers.bootc/v1",
        "kind": "BootcHost",
        "spec": {},
        "status": {
            "booted": {
                "image": {"image": "localhost/fork:gnome", "transport": "containers-storage"}
            },
            "staged": None,
            "rollback": None,
        },
    }
    monkeypatch.setattr(
        OBSERVER, "command", lambda *args, **kwargs: OBSERVER.result("ok", json.dumps(payload), 0)
    )
    assert OBSERVER.json_command(["bootc", "status", "--json"], kind="bootc")["output"] == payload


def test_missing_account_retried_and_identity_verifier_runs_only_once(monkeypatch):
    identity_calls, bootc_calls = [], []
    monkeypatch.setattr(OBSERVER, "file_hash", lambda path: "a" * 64)

    def fake_command(args, **kwargs):
        identity_calls.append(args)
        return OBSERVER.result("ok", "do not expose arbitrary verifier text", 0)

    monkeypatch.setattr(OBSERVER, "command", fake_command)

    def fake_json(args, **kwargs):
        if args[0] == "bootc":
            bootc_calls.append(args)
            return OBSERVER.result("missing") if len(bootc_calls) == 1 else snapshot()["bootc"]
        return snapshot()["lsblk" if args[0] == "lsblk" else "findmnt"]

    monkeypatch.setattr(OBSERVER, "json_command", fake_json)
    monkeypatch.setattr(OBSERVER, "mount_snapshot", lambda deadline: snapshot()["findmnt"])
    monkeypatch.setattr(
        OBSERVER,
        "read_text",
        lambda path, *args: BOOT_ID if "boot_id" in str(path) else "100.0 50.0",
    )
    monkeypatch.setattr(OBSERVER, "kernel_root", lambda: snapshot()["kernel_root"])
    monkeypatch.setattr(OBSERVER, "sessions", lambda deadline: ([], "ok"))
    monkeypatch.setattr(
        OBSERVER, "shells", lambda uid, **kwargs: ([], "absent" if uid is None else "ok")
    )

    def absent(_):
        raise KeyError("no account")

    monkeypatch.setattr(OBSERVER.pwd, "getpwnam", absent)
    observer = OBSERVER.Observer(10000000)
    before = observer.snapshot(0)
    assert before["uid"] is None and before["account_status"] == "absent"
    assert before["bootc"] == OBSERVER.result("missing")
    monkeypatch.setattr(
        OBSERVER.pwd,
        "getpwnam",
        lambda _: SimpleNamespace(pw_uid=1000, pw_gid=1000, pw_dir="/home/canary"),
    )
    monkeypatch.setattr(OBSERVER.os, "getgrouplist", lambda user, gid: [gid, 27])
    monkeypatch.setattr(
        OBSERVER.grp,
        "getgrgid",
        lambda gid: SimpleNamespace(gr_gid=gid, gr_name="canary" if gid == 1000 else "sudo"),
    )
    after = observer.snapshot(1)
    assert after["uid"] == 1000 and after["account_status"] == "ok"
    assert after["bootc"]["status"] == "ok"
    assert before["account_groups_status"] == "absent" and before["account_groups"] == []
    assert after["account_groups_status"] == "ok"
    assert after["account_groups"] == ["canary", "sudo"]
    assert after["account_primary_group"] == "canary"
    assert identity_calls == [["python3", "/usr/libexec/tunaos/fork-identity.py", "/"]]
    assert len(bootc_calls) == 2
    assert "arbitrary verifier text" not in serialized(after)
    monkeypatch.setattr(OBSERVER.os, "getgrouplist", lambda user, gid: [gid])
    later = observer.snapshot(2)
    assert later["account_groups"] == ["canary"]
    assert later["account_groups_status"] == "ok"
    assert len(identity_calls) == 1


def test_only_actual_user_session_bus_settings_read(monkeypatch):
    commands = []

    def fake_command(args, **kwargs):
        commands.append(args)
        return OBSERVER.result("ok", "'file:///actual-user-choice.jpg'", 0)

    monkeypatch.setattr(OBSERVER, "command", fake_command)
    account = SimpleNamespace(pw_uid=1003, pw_dir="/var/home/canary")
    settings, status = OBSERVER.wallpaper(account, [{"pid": 10, "start_ticks": "20"}], 100)
    assert status == "ok" and set(settings) == {"picture-uri", "picture-uri-dark"}
    for args in commands:
        assert args[:6] == ["runuser", "-u", "canary", "--", "env", "-i"]
        assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1003/bus" in args
        assert "XDG_RUNTIME_DIR=/run/user/1003" in args
        assert "HOME=/var/home/canary" in args
        assert not any("GSETTINGS_BACKEND" in arg or "DCONF_PROFILE" in arg for arg in args)
        assert args[-4:-1] == ["gsettings", "get", "org.gnome.desktop.background"]
    commands.clear()
    assert OBSERVER.wallpaper(None, [], 100) == ({}, "not_running")
    assert OBSERVER.wallpaper(account, [], 100) == ({}, "not_running")
    assert commands == []


def test_login_collection_allows_empty_but_not_partial_or_failed_properties(monkeypatch):
    monkeypatch.setattr(
        OBSERVER, "command", lambda *args, **kwargs: OBSERVER.result("empty", None, 0)
    )
    assert OBSERVER.sessions(100) == ([], "ok")
    row = active_session()

    def fake_command(args, **kwargs):
        if "list-sessions" in args:
            return OBSERVER.result("ok", "3 1000 canary seat0", 0)
        assert args == ["loginctl", "show-session", "3", "--no-pager"] + [
            "--property=" + key for key in OBSERVER.SESSION_KEYS
        ]
        return OBSERVER.result("ok", "\n".join(f"{k}={v}" for k, v in row.items()), 0)

    monkeypatch.setattr(OBSERVER, "command", fake_command)
    assert OBSERVER.sessions(100) == ([row], "ok")
    row.pop("Remote")
    assert OBSERVER.sessions(100) == ([], "invalid_data")


def test_shell_start_ticks_parsed_after_parenthesized_name(tmp_path):
    proc = tmp_path / "100"
    proc.mkdir()
    (proc / "comm").write_text("gnome-shell\n")
    # Field 22 (starttime) is index 19 after the parenthesized comm field.
    (proc / "stat").write_text("100 (gnome (shell)) " + " ".join(["S"] + ["0"] * 18 + ["98765"]))
    assert OBSERVER.shells(os.getuid(), tmp_path) == ([{"pid": 100, "start_ticks": "98765"}], "ok")
    (proc / "stat").write_text("truncated")
    assert OBSERVER.shells(os.getuid(), tmp_path)[1] != "ok"


def test_file_hash_is_bounded_and_missing_hash_not_invented(tmp_path):
    path = tmp_path / "sample"
    path.write_bytes(b"test")
    assert (
        OBSERVER.file_hash(path)
        == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    )
    assert OBSERVER.file_hash(tmp_path / "missing") is None
    path.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    assert OBSERVER.file_hash(path) is None


def test_missing_command_does_not_emit_exception_or_inherited_environment(monkeypatch):
    def missing(args, **kwargs):
        assert kwargs["env"] == OBSERVER.ENV
        assert kwargs["stderr"] == OBSERVER.subprocess.DEVNULL
        assert kwargs["stdin"] == OBSERVER.subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        raise FileNotFoundError("secret credential never serialize")

    monkeypatch.setattr(OBSERVER.subprocess, "Popen", missing)
    assert OBSERVER.command(["bootc", "status", "--json"]) == OBSERVER.result("missing")


def test_expired_deadline_launches_no_process(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must not spawn beyond deadline")

    monkeypatch.setattr(OBSERVER.subprocess, "Popen", forbidden)
    assert OBSERVER.command(["bootc", "status", "--json"], deadline=0) == OBSERVER.result(
        "deadline"
    )


@pytest.mark.parametrize("duration", ["0", "-1", "3601"])
def test_runtime_cannot_exceed_one_hour_or_disable_deadline(monkeypatch, duration):
    monkeypatch.setattr(OBSERVER.os, "geteuid", lambda: 0)
    with pytest.raises(SystemExit):
        OBSERVER.main(["--duration", duration])


def test_nonroot_refused_before_touching_serial(monkeypatch):
    monkeypatch.setattr(OBSERVER.os, "geteuid", lambda: 1000)
    with pytest.raises(SystemExit):
        OBSERVER.main([])


def test_main_only_writes_serial_and_stops_by_deadline(monkeypatch):
    clock = [0.0]
    writes, closes, sleeps = [], [], []
    monkeypatch.setattr(OBSERVER.time, "monotonic", lambda: clock[0])

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(OBSERVER.time, "sleep", sleep)
    monkeypatch.setattr(OBSERVER.os, "geteuid", lambda: 0)
    monkeypatch.setattr(OBSERVER, "open_observer_port", lambda: 9)
    monkeypatch.setattr(OBSERVER.os, "close", closes.append)

    class FakeObserver:
        def __init__(self, deadline):
            assert deadline == 5

        def snapshot(self, seq):
            return snapshot(seq)

    monkeypatch.setattr(OBSERVER, "Observer", FakeObserver)
    monkeypatch.setattr(
        OBSERVER, "write_serial", lambda fd, data, deadline: writes.append(data) or True
    )
    assert OBSERVER.main(["--duration", "5"]) == 0
    assert [OBSERVER.latest(row.decode())["seq"] for row in writes] == [0, 1, 2]
    assert sleeps == [2, 2, 1] and clock[0] == 5
    assert OBSERVER.PORT_NAME == "org.tunaos.fork-observer"
    assert closes == [9]


def test_readonly_command_inventory_excludes_auth_and_disk_mutation():
    source = (ROOT / "scripts/fork-install-observer.py").read_text()
    for forbidden in (
        "chpasswd",
        "useradd",
        "usermod",
        "mkfs",
        "wipefs",
        "bootc install",
        "bootc switch",
        "/etc/shadow",
        "/etc/passwd",
        "/environ",
        "gsettings set",
        "GSETTINGS_BACKEND=memory",
    ):
        assert forbidden not in source
    assert "--json" in OBSERVER.LSBLK and "--json" in OBSERVER.FINDMNT
    assert "UUID" in OBSERVER.LSBLK[-1].split(",")
    assert "OPTIONS" not in OBSERVER.FINDMNT[-1].split(",")


@pytest.mark.parametrize(
    "contents,returncode,expected",
    [
        (b"known output\n", 0, OBSERVER.result("ok", "known output", 0)),
        (b"", 0, OBSERVER.result("empty", None, 0)),
        (b"sensitive failure details", 2, OBSERVER.result("command_failed", None, 2)),
        (b"\xff", 0, OBSERVER.result("invalid_utf8", None, 0)),
        (b"x" * (OBSERVER.MAX_OUTPUT + 1), 0, OBSERVER.result("output_limit")),
    ],
)
def test_command_output_limits_and_failures_are_bounded(
    monkeypatch, tmp_path, contents, returncode, expected
):
    stream = (tmp_path / "stdout").open("w+b")
    stream.write(contents)
    stream.seek(0)
    killed = []

    class FakeProcess:
        pid = 900001
        stdout = stream

        def __init__(self):
            self.returncode = None

        def wait(self, timeout=None):
            self.returncode = returncode

        def poll(self):
            return self.returncode

    class FakeSelector:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            self.registered = True

        def unregister(self, *args):
            self.registered = False

        def get_map(self):
            return {1: True} if self.registered else {}

        def select(self, timeout):
            return [True]

    monkeypatch.setattr(OBSERVER.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(OBSERVER.selectors, "DefaultSelector", FakeSelector)
    monkeypatch.setattr(OBSERVER.os, "killpg", lambda pid, sig: killed.append(pid))
    assert OBSERVER.command(["read-only-probe"]) == expected
    assert stream.closed
    assert killed == ([900001] if expected["status"] == "output_limit" else [])


def test_timeout_kills_probe_group_without_recording_partial_output(monkeypatch, tmp_path):
    stream = (tmp_path / "stdout").open("w+b")

    class FakeProcess:
        pid = 900002
        stdout = stream
        returncode = None

        def wait(self, timeout=None):
            self.returncode = -9

        def poll(self):
            return self.returncode

    class TimeoutSelector:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def register(self, *args):
            pass

        def get_map(self):
            return {1: True}

        def select(self, timeout):
            return []

    killed = []
    monkeypatch.setattr(OBSERVER.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(OBSERVER.selectors, "DefaultSelector", TimeoutSelector)
    monkeypatch.setattr(OBSERVER.os, "killpg", lambda pid, sig: killed.append(pid))
    assert OBSERVER.command(["read-only-probe"]) == OBSERVER.result("timeout")
    assert killed == [900002] and stream.closed


def test_shell_scan_honors_sample_deadline(tmp_path):
    (tmp_path / "100").mkdir()
    assert OBSERVER.shells(os.getuid(), tmp_path, deadline=0) == ([], "deadline")


def test_serial_partial_writes_are_bounded(monkeypatch):
    writes = []
    monkeypatch.setattr(OBSERVER.select, "select", lambda *args: ([], [9], []))
    monkeypatch.setattr(
        OBSERVER.os,
        "write",
        lambda fd, value: writes.append(bytes(value[:2])) or min(2, len(value)),
    )
    assert OBSERVER.write_serial(9, b"hello", OBSERVER.time.monotonic() + 5)
    assert b"".join(writes) == b"hello"
    assert not OBSERVER.write_serial(9, b"never", 0)


def test_mount_probes_are_exact_bounded_and_do_not_invent_hierarchy(monkeypatch):
    calls = []
    root = {k: v for k, v in mount_fixture()["filesystems"][0].items() if k != "children"}
    var = mount_fixture()["filesystems"][0]["children"][1]
    # The parent need not be one of these three queried mounts. Preserve it.
    var["parent"] = 999

    def probe(args, **kwargs):
        calls.append(args)
        target = args[-1]
        assert args[-2] == "--mountpoint"
        if target == "/sysroot":
            return OBSERVER.result("command_failed", None, 1)
        return OBSERVER.result("ok", {"filesystems": [root if target == "/" else var]}, 0)

    monkeypatch.setattr(OBSERVER, "json_command", probe)
    observed = OBSERVER.mount_snapshot(100)
    assert observed["status"] == "ok"
    assert observed["output"]["filesystems"] == [root, var]
    assert observed["output"]["mountpoint_status"] == {
        "/": "ok",
        "/sysroot": "not_observed",
        "/var": "ok",
    }
    assert len(calls) == 3 and all("--submounts" not in args for args in calls)
    value = snapshot()
    value["findmnt"] = observed
    value["root_backing"] = OBSERVER.root_backing(value["lsblk"], observed)
    OBSERVER.validate_snapshot(value)
    assert value["root_backing"]["root"]["source"] == "composefs:/"
    assert value["root_backing"]["block_mounts"][0]["mount"]["parent"] == 999


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"target": "/wrong"}],
        [{"target": "/"}, {"target": "/"}],
        [{"target": "/", "children": [{"target": "/unrequested"}]}],
    ],
)
def test_wrong_or_broad_exact_mount_probe_is_rejected(monkeypatch, rows):
    monkeypatch.setattr(
        OBSERVER,
        "json_command",
        lambda *args, **kwargs: OBSERVER.result("ok", {"filesystems": rows}, 0),
    )
    assert OBSERVER.mount_snapshot(100)["status"] == "invalid_data"


def test_missing_actual_root_cannot_be_replaced_by_sysroot(monkeypatch):
    def probe(args, **kwargs):
        if args[-1] == "/":
            return OBSERVER.result("command_failed", None, 1)
        return OBSERVER.result("ok", {"filesystems": [{"target": args[-1]}]}, 0)

    monkeypatch.setattr(OBSERVER, "json_command", probe)
    assert OBSERVER.mount_snapshot(100) == OBSERVER.result("command_failed", None, 1)


@pytest.mark.parametrize("family_gid,family", [(27, "sudo"), (10, "wheel")])
def test_groups_are_actual_nss_memberships_including_primary(monkeypatch, family_gid, family):
    calls = []

    def group_list(user, gid):
        calls.append((user, gid))
        return [family_gid, 1000, family_gid]

    monkeypatch.setattr(OBSERVER.os, "getgrouplist", group_list)
    monkeypatch.setattr(
        OBSERVER.grp,
        "getgrgid",
        lambda gid: SimpleNamespace(
            gr_gid=gid,
            gr_name="canary" if gid == 1000 else family,
            gr_passwd="never-export-password",
            gr_mem=["never-export-other-account"],
        ),
    )
    groups, primary, status = OBSERVER.account_groups(SimpleNamespace(pw_gid=1000), "ok")
    assert (groups, primary, status) == (["canary", family], "canary", "ok")
    assert calls == [("canary", 1000)]
    assert "never-export" not in json.dumps([groups, primary, status])


@pytest.mark.parametrize("status", ["absent", "unavailable", "invalid_data"])
def test_unobserved_account_groups_never_query_or_claim_empty_success(monkeypatch, status):
    def forbidden(*args):
        raise AssertionError("unobserved account must not query groups")

    monkeypatch.setattr(OBSERVER.os, "getgrouplist", forbidden)
    assert OBSERVER.account_groups(None, status) == ([], None, status)


@pytest.mark.parametrize(
    "gids,status",
    [
        ([], "invalid_data"),
        ([27], "invalid_data"),
        ([True, 1000], "invalid_data"),
        ([1000, -1], "invalid_data"),
        ([1000, 2**32 - 1], "invalid_data"),
        ([1000, "27"], "invalid_data"),
        ("1000 27", "invalid_data"),
        (list(range(33)), "output_limit"),
    ],
)
def test_group_id_evidence_is_bounded_and_must_include_primary(monkeypatch, gids, status):
    monkeypatch.setattr(OBSERVER.os, "getgrouplist", lambda *args: gids)
    assert OBSERVER.account_groups(SimpleNamespace(pw_gid=1000), "ok") == ([], None, status)


@pytest.mark.parametrize("primary", [True, -1, "1000", 2**32 - 1])
def test_invalid_primary_gid_cannot_earn_group_success(monkeypatch, primary):
    def forbidden(*args):
        raise AssertionError("invalid primary GID must not query NSS")

    monkeypatch.setattr(OBSERVER.os, "getgrouplist", forbidden)
    assert OBSERVER.account_groups(SimpleNamespace(pw_gid=primary), "ok") == (
        [],
        None,
        "invalid_data",
    )


@pytest.mark.parametrize("name", ["canary\nwheel", "a" * 65, "", "sudo:secret", "canary group"])
def test_group_names_cannot_inject_unbounded_or_arbitrary_data(monkeypatch, name):
    monkeypatch.setattr(OBSERVER.os, "getgrouplist", lambda *args: [1000])
    monkeypatch.setattr(
        OBSERVER.grp, "getgrgid", lambda gid: SimpleNamespace(gr_gid=gid, gr_name=name)
    )
    assert OBSERVER.account_groups(SimpleNamespace(pw_gid=1000), "ok") == ([], None, "invalid_data")


@pytest.mark.parametrize("failure", [KeyError("secret NSS detail"), OSError("secret NSS detail")])
def test_missing_group_resolution_exposes_no_partial_membership(monkeypatch, failure):
    monkeypatch.setattr(OBSERVER.os, "getgrouplist", lambda *args: [1000, 27])

    def get_group(gid):
        if gid == 27:
            raise failure
        return SimpleNamespace(gr_gid=1000, gr_name="canary")

    monkeypatch.setattr(OBSERVER.grp, "getgrgid", get_group)
    assert OBSERVER.account_groups(SimpleNamespace(pw_gid=1000), "ok") == ([], None, "unavailable")


@pytest.mark.parametrize(
    "change",
    [
        {"account_groups": ["sudo", "canary"]},
        {"account_groups": ["canary", "canary"]},
        {"account_groups": []},
        {"account_groups": "canary sudo"},
        {"account_groups": ["canary", None]},
        {"account_groups": ["canary", "bad\nname"]},
        {"account_groups": ["canary"] * 33},
        {"account_primary_group": None},
        {"account_primary_group": "wheel"},
        {"account_groups_status": "absent"},
        {"account_groups_status": "unavailable"},
        {"account_groups_status": "passed"},
        {"uid": None, "account_status": "absent"},
    ],
)
def test_group_snapshot_parser_rejects_inconsistent_or_unbounded_evidence(change):
    value = snapshot()
    value.update(
        uid=1000,
        account_status="ok",
        account_groups_status="ok",
        account_primary_group="canary",
        account_groups=["canary", "sudo"],
    )
    value.update(change)
    with pytest.raises(ValueError):
        OBSERVER.parse_lines(serialized(value))


def test_group_snapshot_unavailable_is_honest_but_never_empty_success():
    value = snapshot()
    value.update(uid=1000, account_status="ok", account_groups_status="unavailable")
    assert OBSERVER.latest(serialized(value))["account_groups_status"] == "unavailable"
    value["account_groups_status"] = "ok"
    with pytest.raises(ValueError):
        OBSERVER.latest(serialized(value))


def test_duplicate_group_names_or_mismatched_gid_rejected(monkeypatch):
    monkeypatch.setattr(OBSERVER.os, "getgrouplist", lambda *args: [1000, 27])
    monkeypatch.setattr(
        OBSERVER.grp, "getgrgid", lambda gid: SimpleNamespace(gr_gid=gid, gr_name="canary")
    )
    assert OBSERVER.account_groups(SimpleNamespace(pw_gid=1000), "ok") == ([], None, "invalid_data")
    monkeypatch.setattr(
        OBSERVER.grp, "getgrgid", lambda gid: SimpleNamespace(gr_gid=gid + 1, gr_name="canary")
    )
    assert OBSERVER.account_groups(SimpleNamespace(pw_gid=1000), "ok") == ([], None, "invalid_data")


def test_unavailable_nss_memberships_never_publish_guessed_groups(monkeypatch):
    def unavailable(*args):
        raise OSError("arbitrary diagnostic")

    monkeypatch.setattr(OBSERVER.os, "getgrouplist", unavailable)
    assert OBSERVER.account_groups(SimpleNamespace(pw_gid=1000), "ok") == ([], None, "unavailable")


def test_real_loginctl_property_filter_against_private_bus():
    """Use the installed CLI parser, never a fake command blessing our argv."""
    system_python = Path("/usr/bin/python3")
    required = ("loginctl", "dbus-daemon")

    def unavailable(reason):
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail(reason)  # The standard Ubuntu CI lane must run this gate.
        pytest.skip(reason)

    if not system_python.is_file() or any(shutil.which(name) is None for name in required):
        unavailable("real loginctl test needs system Python, loginctl and dbus-daemon")
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    available = subprocess.run(
        [str(system_python), "-c", "from gi.repository import Gio, GLib"],
        check=False,
        env=env,
        capture_output=True,
        timeout=5,
    )
    if available.returncode:
        unavailable("real loginctl test needs the system Python gi/Gio installation")
    fixture = ROOT / "tests/fixtures/fork-login/loginctl_private_bus.py"
    process = subprocess.Popen(
        [str(system_python), str(fixture), str(ROOT / "scripts/fork-install-observer.py")],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode == 77:
            unavailable("local sandbox denies private D-Bus Unix socket creation (EPERM)")
        assert process.returncode == 0, (stdout + stderr)[-8192:]
        assert "PASS: real loginctl comma negative control" in stdout
        rows = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
        assert len(rows) == 2 and {row["legacy_list"] for row in rows} == {False, True}
        assert all(row["observer_status"] == "ok" for row in rows)
    finally:
        # Also reap the private daemon if the fixture exits early or times out.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


@pytest.fixture
def private_port(monkeypatch):
    state = SimpleNamespace(
        target="../vport0p1",
        name=OBSERVER.PORT_NAME,
        device_number="0:3",
        opens=[],
        closes=[],
        expected=SimpleNamespace(st_mode=0o020600, st_dev=1, st_ino=2, st_rdev=3),
    )
    state.actual = copy.copy(state.expected)
    fake_os = SimpleNamespace(**vars(os))

    def readlink(path):
        assert path == OBSERVER.PORT_PATH
        if state.target is None:
            raise FileNotFoundError
        return state.target

    def read_name(path, limit):
        if path == Path("/sys/class/virtio-ports/vport0p1/dev"):
            assert limit == 64
            return state.device_number
        assert path == Path("/sys/class/virtio-ports/vport0p1/name") and limit == 128
        return state.name

    def stat_node(path, *, follow_symlinks):
        assert path == Path("/dev/vport0p1") and follow_symlinks is False
        return state.expected

    fake_os.readlink = readlink
    fake_os.stat = stat_node
    fake_os.open = lambda path, flags: state.opens.append((path, flags)) or 9
    fake_os.fstat = lambda fd: state.actual
    fake_os.close = state.closes.append
    monkeypatch.setattr(OBSERVER, "os", fake_os)
    monkeypatch.setattr(OBSERVER, "read_text", read_name)
    return state


def test_private_observer_port_requires_exact_named_character_device(private_port):
    state = private_port
    assert OBSERVER.open_observer_port() == 9
    assert len(state.opens) == 1 and state.opens[0][0] == Path("/dev/vport0p1")
    flags = state.opens[0][1]
    for flag in (os.O_WRONLY, os.O_NONBLOCK, os.O_NOCTTY, os.O_NOFOLLOW):
        assert flags & flag
    assert state.closes == []


def test_missing_private_port_never_opens_console(private_port):
    private_port.target = None
    assert OBSERVER.open_observer_port() is None
    assert private_port.opens == [] and private_port.closes == []


@pytest.mark.parametrize(
    "target",
    [
        "/dev/vport0p1",
        "../../dev/vport0p1",
        "../nested/vport0p1",
        "../ttyS0",
        "../vport0p1/../ttyS0",
        "../vport0p1\n",
        "vport0p1",
        "../vportxp1",
        "",
    ],
)
def test_other_symlink_routes_are_refused_without_open(private_port, target):
    private_port.target = target
    with pytest.raises(ValueError, match="unexpected observer port target"):
        OBSERVER.open_observer_port()
    assert private_port.opens == []


@pytest.mark.parametrize("mode", [0o100600, 0o120777, 0o060600, 0o010600])
def test_private_port_target_must_be_character_device(private_port, mode):
    private_port.expected.st_mode = mode
    with pytest.raises(ValueError, match="not a character device"):
        OBSERVER.open_observer_port()
    assert private_port.opens == []


def test_private_port_rejects_other_sysfs_name(private_port):
    private_port.name = "org.other.port"
    with pytest.raises(ValueError, match="name mismatch"):
        OBSERVER.open_observer_port()
    assert private_port.opens == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("st_mode", 0o100600),
        ("st_dev", 4),
        ("st_ino", 5),
        ("st_rdev", 6),
    ],
)
def test_private_port_fd_is_bound_to_checked_character_device(private_port, field, value):
    setattr(private_port.actual, field, value)
    with pytest.raises(ValueError, match="changed while opening"):
        OBSERVER.open_observer_port()
    assert len(private_port.opens) == 1 and private_port.closes == [9]


@pytest.mark.parametrize("changed", ["target", "name"])
def test_private_port_rechecks_alias_and_name_after_open(private_port, changed):
    state = private_port

    def replace(path, flags):
        state.opens.append((path, flags))
        setattr(state, changed, "../vport0p2" if changed == "target" else "other-port")
        return 9

    OBSERVER.os.open = replace
    with pytest.raises(ValueError, match="changed while opening"):
        OBSERVER.open_observer_port()
    assert state.closes == [9]


@pytest.mark.parametrize("duration,expected_wait", [(60, 30), (5, 5)])
def test_absent_port_discovery_is_bounded_and_runs_no_collectors(
    monkeypatch, duration, expected_wait
):
    clock, attempts = [0.0], []
    monkeypatch.setattr(OBSERVER.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        OBSERVER.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )
    monkeypatch.setattr(OBSERVER.os, "geteuid", lambda: 0)
    monkeypatch.setattr(OBSERVER, "open_observer_port", lambda: attempts.append(clock[0]))
    monkeypatch.setattr(OBSERVER, "Observer", lambda _: pytest.fail("no collectors without port"))
    assert OBSERVER.main(["--duration", str(duration)]) == 0
    assert clock[0] == expected_wait and len(attempts) == expected_wait


def test_private_port_udev_delay_consumes_original_duration_budget(monkeypatch):
    clock, attempts, writes = [0.0], [], []
    monkeypatch.setattr(OBSERVER.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        OBSERVER.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )
    monkeypatch.setattr(OBSERVER.os, "geteuid", lambda: 0)
    monkeypatch.setattr(OBSERVER.os, "close", lambda _: None)

    def port():
        attempts.append(clock[0])
        return 9 if clock[0] >= 3 else None

    monkeypatch.setattr(OBSERVER, "open_observer_port", port)
    monkeypatch.setattr(OBSERVER, "Observer", lambda end: SimpleNamespace(snapshot=snapshot))
    monkeypatch.setattr(OBSERVER, "write_serial", lambda *args: writes.append(args) or True)
    assert OBSERVER.main(["--duration", "5"]) == 0
    assert attempts == [0, 1, 2, 3] and clock[0] == 5
    assert len(writes) == 1 and writes[0][2] == 5


@pytest.mark.parametrize("device_number", ["0:4", "1:3", "bad", "0:3\n", "0:03:4"])
def test_private_port_character_number_must_match_sysfs(private_port, device_number):
    private_port.device_number = device_number
    with pytest.raises(ValueError, match="sysfs"):
        OBSERVER.open_observer_port()
    assert private_port.opens == []


def test_private_port_sysfs_device_number_rechecked_after_open(private_port):
    state = private_port

    def replace(path, flags):
        state.opens.append((path, flags))
        state.device_number = "0:4"
        return 9

    OBSERVER.os.open = replace
    with pytest.raises(ValueError, match="changed while opening"):
        OBSERVER.open_observer_port()
    assert state.closes == [9]
