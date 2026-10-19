#!/usr/bin/env python3
"""Read-only serial evidence for disposable fork-install qualification canaries.

Install only in the finalized qualification image, never a production image.
The service must run as root after multi-user.target. It creates no accounts,
passwords, sessions, mounts, or disk state. The only write is bounded evidence
on /dev/ttyS0. A snapshot is evidence, never installation authorization.

Root mounts are not rewritten: composefs:/ remains composefs:/. Independently
matched block mounts at /sysroot or /var are candidates, not an assertion that
they back the running root. Consumers must prove the required relationship.
"""

import argparse
import grp
import hashlib
import json
import math
import os
import pwd
import re
import select
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

PREFIX = "TUNAOS_FORK_INSTALL_OBSERVATION="
SCHEMA = "tunaos.fork-install-observer"
VERSION = 2
USER = "canary"
INTERVAL = 2.0
MAX_DURATION = 3600
MAX_ROW = 65535
MAX_OUTPUT = 16384
MAX_SESSIONS = 32
MAX_SHELLS = 32
MAX_GROUPS = 32
SESSION_KEYS = (
    "Id",
    "User",
    "Name",
    "Remote",
    "Type",
    "Class",
    "Active",
    "State",
    "Service",
    "Desktop",
    "Seat",
    "Leader",
    "LockedHint",
    "TimestampMonotonic",
)
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
BOOT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SESSION_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")
GROUP_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}\Z")
STATUSES = {
    "ok",
    "missing",
    "timeout",
    "command_failed",
    "output_limit",
    "invalid_utf8",
    "invalid_json",
    "invalid_data",
    "empty",
    "unavailable",
    "deadline",
}
LSBLK = [
    "lsblk",
    "--json",
    "--bytes",
    "--paths",
    "--output",
    "NAME,KNAME,PATH,TYPE,SIZE,RO,SERIAL,MAJ:MIN,PKNAME,MOUNTPOINTS,FSTYPE,PTTYPE,UUID",
]
FINDMNT = ["findmnt", "--json", "--output", "TARGET,SOURCE,FSTYPE,FSROOT,ID,PARENT,MAJ:MIN"]
MOUNTPOINTS = ("/", "/sysroot", "/var")


def result(status, output=None, returncode=None):
    return {"status": status, "returncode": returncode, "output": output}


def command(args, *, deadline=None, timeout=1.5):
    """Capture bounded stdout only, discarding all arbitrary diagnostic text."""
    end = min(time.monotonic() + timeout, deadline if deadline is not None else math.inf)
    if end <= time.monotonic():
        return result("deadline")
    try:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=ENV,
            start_new_session=True,
        )
    except FileNotFoundError:
        return result("missing")
    except OSError:
        return result("unavailable")
    chunks = bytearray()
    failure = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    failure = "timeout"
                    break
                if not selector.select(remaining):
                    failure = "timeout"
                    break
                chunk = os.read(proc.stdout.fileno(), min(4096, MAX_OUTPUT + 1 - len(chunks)))
                if not chunk:
                    selector.unregister(proc.stdout)
                else:
                    chunks.extend(chunk)
                    if len(chunks) > MAX_OUTPUT:
                        failure = "output_limit"
                        break
        if failure is None:
            try:
                proc.wait(timeout=max(0.001, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                failure = "timeout"
        if failure:
            return result(failure)
        if proc.returncode != 0:
            return result("command_failed", returncode=proc.returncode)
        try:
            output = chunks.decode("utf-8").strip()
        except UnicodeDecodeError:
            return result("invalid_utf8", returncode=0)
        return result("ok" if output else "empty", output or None, 0)
    except OSError:
        return result("unavailable")
    finally:
        # Kill only the process group created for this read-only probe, including
        # a stuck runuser/gsettings descendant; never leave a probe behind.
        if proc.poll() is None or failure:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait()
        proc.stdout.close()


def strict_json(text):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def invalid(_):
        raise ValueError("non-finite JSON value")

    return json.loads(text, object_pairs_hook=unique, parse_constant=invalid)


def json_command(args, *, deadline=None, kind):
    value = command(args, deadline=deadline)
    if value["status"] != "ok":
        return value
    try:
        output = strict_json(value["output"])
        if not isinstance(output, dict) or not output:
            raise ValueError("non-object JSON")
        if kind == "bootc":
            if not isinstance(output.get("status"), dict) or "booted" not in output["status"]:
                raise ValueError("missing bootc status")
        elif not isinstance(output.get(kind), list) or not output[kind]:
            raise ValueError("missing observation tree")
        value["output"] = output
    except (ValueError, RecursionError):
        return result("invalid_json", returncode=0)
    return value


def read_text(path, limit=4096):
    with Path(path).open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("file output limit")
    return value.decode("utf-8").strip()


def file_hash(path):
    try:
        digest = hashlib.sha256()
        total = 0
        with Path(path).open("rb") as stream:
            while chunk := stream.read(65536):
                total += len(chunk)
                if total > 4 * 1024 * 1024:
                    return None
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def kernel_root():
    """Return only an admitted root token; never disclose the command line."""
    empty = {"kind": None, "value": None}
    try:
        tokens = [
            word[5:]
            for word in read_text("/proc/cmdline", 65536).split()
            if word.startswith("root=")
        ]
    except (OSError, ValueError):
        return {"status": "unavailable", **empty}
    if not tokens:
        return {"status": "missing", **empty}
    if len(tokens) != 1:
        return {"status": "ambiguous", **empty}
    if re.fullmatch(r"UUID=[0-9A-Fa-f]+(?:-[0-9A-Fa-f]+)*", tokens[0]):
        return {"status": "ok", "kind": "uuid", "value": tokens[0][5:]}
    if re.fullmatch(r"/dev/[A-Za-z0-9][A-Za-z0-9_.+-]*", tokens[0]):
        return {"status": "ok", "kind": "device", "value": tokens[0]}
    return {"status": "unsupported", **empty}


def sessions(deadline):
    listed = command(["loginctl", "list-sessions", "--no-legend", "--no-pager"], deadline=deadline)
    if listed["status"] == "empty":
        return [], "ok"
    if listed["status"] != "ok":
        return [], listed["status"]
    ids = [row.split()[0] for row in listed["output"].splitlines() if row.strip()]
    if (
        len(ids) > MAX_SESSIONS
        or len(ids) != len(set(ids))
        or any(not SESSION_ID.fullmatch(s) for s in ids)
    ):
        return [], "invalid_data"
    found = []
    for sid in ids:
        got = command(
            ["loginctl", "show-session", sid, "--no-pager", "--property=" + ",".join(SESSION_KEYS)],
            deadline=deadline,
        )
        if got["status"] != "ok":
            return [], got["status"]
        values = {}
        for row in got["output"].splitlines():
            key, sep, value = row.partition("=")
            if not sep or key not in SESSION_KEYS or key in values or len(value) > 256:
                return [], "invalid_data"
            values[key] = value
        if set(values) != set(SESSION_KEYS) or values["Id"] != sid:
            return [], "invalid_data"
        found.append(values)
    return found, "ok"


def shells(uid, proc_root=Path("/proc"), *, deadline=None):
    if uid is None:
        return [], "absent"
    found = []
    try:
        for proc in proc_root.iterdir():
            if deadline is not None and time.monotonic() >= deadline:
                return [], "deadline"
            if not proc.name.isdigit():
                continue
            try:
                if proc.stat().st_uid != uid or read_text(proc / "comm", 256) != "gnome-shell":
                    continue
                fields = read_text(proc / "stat").rsplit(")", 1)[1].split()
                if len(fields) < 20 or not fields[19].isdigit():
                    return [], "invalid_data"
                found.append({"pid": int(proc.name), "start_ticks": fields[19]})
                if len(found) > MAX_SHELLS:
                    return [], "output_limit"
            except FileNotFoundError:
                continue  # Normal exit race; never fabricate a shell from stale data.
            except (OSError, ValueError, IndexError):
                return [], "unavailable"
    except OSError:
        return [], "unavailable"
    return sorted(found, key=lambda item: item["pid"]), "ok"


def wallpaper(account, running_shells, deadline):
    if account is None or not running_shells:
        return {}, "not_running"
    if not account.pw_dir.startswith("/") or any(ord(c) < 32 for c in account.pw_dir):
        return {}, "invalid_data"
    values = {}
    for key in ("picture-uri", "picture-uri-dark"):
        got = command(
            [
                "runuser",
                "-u",
                USER,
                "--",
                "env",
                "-i",
                "PATH=" + ENV["PATH"],
                "HOME=" + account.pw_dir,
                "USER=" + USER,
                "LOGNAME=" + USER,
                f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{account.pw_uid}/bus",
                f"XDG_RUNTIME_DIR=/run/user/{account.pw_uid}",
                "gsettings",
                "get",
                "org.gnome.desktop.background",
                key,
            ],
            deadline=deadline,
        )
        if got["status"] != "ok":
            return {}, got["status"]
        if len(got["output"]) > 2048:
            return {}, "output_limit"
        values[key] = got["output"]
    return values, "ok"


def mount_snapshot(deadline):
    """Query exact mountpoints; broad Flatpak mount trees exceed serial budgets.

    ID and PARENT are retained as reported, not inferred from pathname nesting.
    A return code of one only says that the requested mount was not observed;
    it is never used as proof that a path or backing device does not exist.
    """
    filesystems, statuses = [], {}
    root_result = None
    for target in MOUNTPOINTS:
        got = json_command(
            FINDMNT + ["--mountpoint", target], deadline=deadline, kind="filesystems"
        )
        if got["status"] == "ok":
            rows = got["output"]["filesystems"]
            if (
                len(rows) != 1
                or not isinstance(rows[0], dict)
                or rows[0].get("target") != target
                or rows[0].get("children")
            ):
                return result("invalid_data", returncode=0)
            filesystems.append(rows[0])
        statuses[target] = (
            "not_observed"
            if got["status"] == "command_failed" and got["returncode"] == 1
            else got["status"]
        )
        if target == "/":
            root_result = got
    if root_result["status"] != "ok":
        return root_result
    return result("ok", {"filesystems": filesystems, "mountpoint_status": statuses}, 0)


def root_backing(blocks, mounts):
    """Expose observed correlations, never infer a composefs device substitution."""
    empty = {"status": "unavailable", "root": None, "block_mounts": []}
    if blocks["status"] != "ok" or mounts["status"] != "ok":
        return empty
    devices, filesystems = [], []

    def walk(nodes, sink, ancestors=(), depth=0):
        if depth > 32 or not isinstance(nodes, list):
            raise ValueError("invalid tree")
        for node in nodes:
            if not isinstance(node, dict) or len(sink) > 512:
                raise ValueError("invalid tree")
            sink.append((node, ancestors))
            walk(node.get("children", []), sink, ancestors + (node,), depth + 1)

    try:
        walk(blocks["output"]["blockdevices"], devices)
        walk(mounts["output"]["filesystems"], filesystems)
        roots = [node for node, _ in filesystems if node.get("target") == "/"]
        if len(roots) != 1:
            raise ValueError("ambiguous root")
        root = {k: v for k, v in roots[0].items() if k != "children"}
        matched = []
        for mount, _ in filesystems:
            if mount.get("target") not in ("/", "/sysroot", "/var"):
                continue
            number = mount.get("maj:min")
            matches = [
                (node, parents)
                for node, parents in devices
                if number and node.get("maj:min") == number
            ]
            if len(matches) > 1:
                raise ValueError("ambiguous device")
            if not matches:
                continue
            node, parents = matches[0]
            source = mount.get("source")
            path = node.get("path")
            # findmnt records a subvolume root as /dev/vda3[/ostree/...]. Keep
            # that observed source, while matching its explicit block path.
            if (
                not isinstance(path, str)
                or not isinstance(source, str)
                or not (source == path or source.startswith(path + "["))
            ):
                continue
            if mount["target"] not in (node.get("mountpoints") or []):
                continue
            chain = parents + (node,)
            if chain[0].get("type") != "disk":
                continue
            matched.append(
                {
                    "mount": {k: v for k, v in mount.items() if k != "children"},
                    "device_path": path,
                    "ancestry": [
                        {k: item.get(k) for k in ("path", "type", "maj:min", "pkname", "serial")}
                        for item in chain
                    ],
                }
            )
        status = "block_root" if any(m["mount"]["target"] == "/" for m in matched) else "unresolved"
        if (
            status == "unresolved"
            and (root.get("fstype") == "composefs" or root.get("source") == "composefs:/")
            and matched
        ):
            status = "composefs_candidates"
        return {"status": status, "root": root, "block_mounts": matched}
    except (KeyError, TypeError, ValueError, RecursionError):
        return {**empty, "status": "invalid_data"}


def account_groups(account, account_status):
    """Read this account's actual NSS groups; never infer recipe/default groups."""
    if account is None:
        return [], None, account_status
    try:
        primary_gid = account.pw_gid
        if type(primary_gid) is not int or not 0 <= primary_gid < 2**32 - 1:
            return [], None, "invalid_data"
        gids = os.getgrouplist(USER, primary_gid)
        if not isinstance(gids, (list, tuple)) or not gids:
            return [], None, "invalid_data"
        if len(gids) > MAX_GROUPS:
            return [], None, "output_limit"
        if any(type(gid) is not int or not 0 <= gid < 2**32 - 1 for gid in gids):
            return [], None, "invalid_data"
        if primary_gid not in gids:
            return [], None, "invalid_data"
        names = {}
        for gid in set(gids):
            entry = grp.getgrgid(gid)
            name = entry.gr_name
            if (
                type(entry.gr_gid) is not int
                or entry.gr_gid != gid
                or not isinstance(name, str)
                or not GROUP_NAME.fullmatch(name)
            ):
                return [], None, "invalid_data"
            names[gid] = name
        if len(set(names.values())) != len(names):
            return [], None, "invalid_data"
        return sorted(names.values()), names[primary_gid], "ok"
    except (KeyError, OSError):
        return [], None, "unavailable"


class Observer:
    def __init__(self, deadline):
        self.deadline = deadline
        self.observer_sha256 = file_hash(Path(__file__))
        self.fork_config_sha256 = file_hash("/usr/share/tunaos/fork/fork-config.json")
        checked = command(
            ["python3", "/usr/libexec/tunaos/fork-identity.py", "/"], deadline=deadline, timeout=15
        )
        # The verifier's exit code is evidence. Its narrative output is not.
        self.identity_verifier = {
            "status": "ok" if checked["status"] == "empty" else checked["status"],
            "returncode": checked["returncode"],
        }

    def snapshot(self, seq):
        # Leave a small part of each interval for framing and serial delivery.
        deadline = min(self.deadline, time.monotonic() + INTERVAL * 0.9)
        errors = []
        try:
            boot_id = read_text("/proc/sys/kernel/random/boot_id", 64)
            uptime = float(read_text("/proc/uptime", 128).split()[0])
            if not BOOT_ID.fullmatch(boot_id) or not math.isfinite(uptime) or uptime < 0:
                raise ValueError("invalid boot clock")
        except (OSError, ValueError, IndexError):
            boot_id, uptime = None, None
            errors.append("boot_clock_unavailable")
        try:
            account = pwd.getpwnam(USER)
            account_status = "ok"
            if account.pw_uid <= 0:
                account, account_status = None, "invalid_data"
        except KeyError:
            account, account_status = None, "absent"
        except OSError:
            account, account_status = None, "unavailable"
        uid = account.pw_uid if account is not None else None
        groups, primary_group, groups_status = account_groups(account, account_status)
        bootc = json_command(["bootc", "status", "--json"], deadline=deadline, kind="bootc")
        blocks = json_command(LSBLK, deadline=deadline, kind="blockdevices")
        mounts = mount_snapshot(deadline)
        logins, sessions_status = sessions(deadline)
        running_shells, shells_status = shells(uid, deadline=deadline)
        settings, wallpaper_status = wallpaper(account, running_shells, deadline)
        return {
            "schema": SCHEMA,
            "schema_version": VERSION,
            "seq": seq,
            "observer_sha256": self.observer_sha256,
            "fork_config_sha256": self.fork_config_sha256,
            "boot_id": boot_id,
            "uptime": uptime,
            "uid": uid,
            "account_status": account_status,
            "account_groups": groups,
            "account_primary_group": primary_group,
            "account_groups_status": groups_status,
            "sessions": logins,
            "sessions_status": sessions_status,
            "gnome_shell": running_shells,
            "gnome_shell_status": shells_status,
            "wallpaper": settings,
            "wallpaper_status": wallpaper_status,
            "bootc": bootc,
            "lsblk": blocks,
            "findmnt": mounts,
            "identity_verifier": self.identity_verifier,
            "root_backing": root_backing(blocks, mounts),
            "kernel_root": kernel_root(),
            "errors": errors,
        }


def encode_snapshot(snapshot):
    """An oversized observation is explicitly unusable, never a truncated pass."""
    encoded = (
        PREFIX
        + json.dumps(snapshot, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("ascii")
    if len(encoded) > MAX_ROW:
        small = dict(snapshot)
        small.update(
            {
                "bootc": result("output_limit"),
                "lsblk": result("output_limit"),
                "findmnt": result("output_limit"),
                "sessions": [],
                "sessions_status": "output_limit",
                "gnome_shell": [],
                "gnome_shell_status": "output_limit",
                "wallpaper": {},
                "wallpaper_status": "output_limit",
                "root_backing": {"status": "unavailable", "root": None, "block_mounts": []},
                "errors": ["snapshot_output_limit"],
            }
        )
        encoded = (
            PREFIX
            + json.dumps(small, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
            + "\n"
        ).encode("ascii")
    if len(encoded) > MAX_ROW:
        raise ValueError("observation metadata exceeds row limit")
    return encoded


def validate_snapshot(value):
    """Validate framing/schema; availability and qualification remain explicit."""
    if (
        not isinstance(value, dict)
        or value.get("schema") != SCHEMA
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != VERSION
    ):
        raise ValueError("unsupported observer schema")
    expected = {
        "schema",
        "schema_version",
        "seq",
        "observer_sha256",
        "fork_config_sha256",
        "boot_id",
        "uptime",
        "uid",
        "account_status",
        "account_groups",
        "account_primary_group",
        "account_groups_status",
        "sessions",
        "sessions_status",
        "gnome_shell",
        "gnome_shell_status",
        "wallpaper",
        "wallpaper_status",
        "bootc",
        "lsblk",
        "findmnt",
        "identity_verifier",
        "root_backing",
        "kernel_root",
        "errors",
    }
    if set(value) != expected:
        raise ValueError("unexpected observer fields")
    if type(value.get("seq")) is not int or value["seq"] < 0:
        raise ValueError("invalid observer sequence")
    if not isinstance(value.get("boot_id"), str) or not BOOT_ID.fullmatch(value["boot_id"]):
        raise ValueError("invalid observer boot ID")
    if (
        type(value.get("uptime")) not in (float, int)
        or not math.isfinite(value["uptime"])
        or value["uptime"] < 0
    ):
        raise ValueError("invalid observer uptime")
    for key in ("observer_sha256", "fork_config_sha256"):
        if not isinstance(value.get(key), str) or not SHA256.fullmatch(value[key]):
            raise ValueError("missing observer identity hashes")
    uid = value.get("uid")
    if uid is not None and (type(uid) is not int or uid <= 0):
        raise ValueError("invalid observer user ID")
    if value.get("account_status") not in ("ok", "absent", "unavailable", "invalid_data") or (
        (value["account_status"] == "ok") != (uid is not None)
    ):
        raise ValueError("inconsistent observer account")
    groups = value["account_groups"]
    primary = value["account_primary_group"]
    groups_status = value["account_groups_status"]
    if (
        groups_status not in ("ok", "absent", "unavailable", "invalid_data", "output_limit")
        or not isinstance(groups, list)
        or len(groups) > MAX_GROUPS
        or any(not isinstance(group, str) or not GROUP_NAME.fullmatch(group) for group in groups)
        or groups != sorted(set(groups))
    ):
        raise ValueError("invalid observer account groups")
    if groups_status == "ok":
        if value["account_status"] != "ok" or not groups or primary not in groups:
            raise ValueError("inconsistent observer account groups")
    elif groups or primary is not None:
        raise ValueError("failed group observation contains data")
    if (uid is None and groups_status != value["account_status"]) or (
        uid is not None and groups_status == "absent"
    ):
        raise ValueError("inconsistent observer account group availability")
    for key, root_key in (
        ("bootc", "status"),
        ("lsblk", "blockdevices"),
        ("findmnt", "filesystems"),
    ):
        item = value.get(key)
        if (
            not isinstance(item, dict)
            or set(item) != {"status", "returncode", "output"}
            or item["status"] not in STATUSES
        ):
            raise ValueError("invalid observer command result")
        if item["returncode"] is not None and type(item["returncode"]) is not int:
            raise ValueError("invalid command return code")
        if item["status"] == "ok":
            if (
                item["returncode"] != 0
                or not isinstance(item["output"], dict)
                or not item["output"].get(root_key)
            ):
                raise ValueError("empty successful command evidence")
            if key == "bootc" and (
                not isinstance(item["output"]["status"], dict)
                or "booted" not in item["output"]["status"]
            ):
                raise ValueError("invalid bootc evidence")
            if key != "bootc" and not isinstance(item["output"][root_key], list):
                raise ValueError("invalid device or mount evidence")
        elif item["output"] is not None:
            raise ValueError("failed command contains output")
    mount_output = value["findmnt"]["output"]
    if value["findmnt"]["status"] == "ok" and "mountpoint_status" in mount_output:
        statuses = mount_output["mountpoint_status"]
        if (
            not isinstance(statuses, dict)
            or set(statuses) != set(MOUNTPOINTS)
            or statuses.get("/") != "ok"
            or any(s not in STATUSES | {"not_observed"} for s in statuses.values())
        ):
            raise ValueError("invalid exact mountpoint statuses")
        targets = [
            row.get("target") for row in mount_output["filesystems"] if isinstance(row, dict)
        ]
        if len(targets) != len(set(targets)) or set(targets) != {
            p for p, s in statuses.items() if s == "ok"
        }:
            raise ValueError("mountpoint statuses differ from observed mounts")
    for key, allowed in (
        ("sessions_status", STATUSES),
        ("gnome_shell_status", STATUSES | {"absent"}),
        ("wallpaper_status", STATUSES | {"not_running"}),
    ):
        if value.get(key) not in allowed:
            raise ValueError("invalid collector status")
    rows = value.get("sessions")
    if not isinstance(rows, list) or len(rows) > MAX_SESSIONS:
        raise ValueError("invalid session evidence")
    ids = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != set(SESSION_KEYS)
            or any(not isinstance(v, str) or len(v) > 256 for v in row.values())
        ):
            raise ValueError("invalid session properties")
        if not SESSION_ID.fullmatch(row["Id"]):
            raise ValueError("invalid session ID")
        ids.append(row["Id"])
    if len(ids) != len(set(ids)) or (rows and value["sessions_status"] != "ok"):
        raise ValueError("inconsistent session evidence")
    processes = value.get("gnome_shell")
    if not isinstance(processes, list) or len(processes) > MAX_SHELLS:
        raise ValueError("invalid shell evidence")
    for process in processes:
        if (
            not isinstance(process, dict)
            or set(process) != {"pid", "start_ticks"}
            or type(process["pid"]) is not int
            or process["pid"] <= 0
            or not isinstance(process["start_ticks"], str)
            or not process["start_ticks"].isdigit()
        ):
            raise ValueError("invalid shell identity")
    if len({p["pid"] for p in processes}) != len(processes) or (
        processes and (uid is None or value["gnome_shell_status"] != "ok")
    ):
        raise ValueError("inconsistent shell evidence")
    settings = value.get("wallpaper")
    if not isinstance(settings, dict) or any(
        k not in ("picture-uri", "picture-uri-dark") or not isinstance(v, str) or len(v) > 2048
        for k, v in settings.items()
    ):
        raise ValueError("invalid wallpaper evidence")
    if (
        value["wallpaper_status"] == "ok"
        and (set(settings) != {"picture-uri", "picture-uri-dark"} or not processes)
    ) or (value["wallpaper_status"] != "ok" and settings):
        raise ValueError("inconsistent wallpaper evidence")
    identity = value.get("identity_verifier")
    if (
        not isinstance(identity, dict)
        or set(identity) != {"status", "returncode"}
        or identity["status"] not in STATUSES
        or (identity["returncode"] is not None and type(identity["returncode"]) is not int)
        or (identity["status"] == "ok" and identity["returncode"] != 0)
    ):
        raise ValueError("invalid identity verifier result")
    kernel = value.get("kernel_root")
    if not isinstance(kernel, dict) or set(kernel) != {"status", "kind", "value"}:
        raise ValueError("invalid kernel root evidence")
    if kernel["status"] == "ok":
        pattern = {
            "uuid": r"[0-9A-Fa-f]+(?:-[0-9A-Fa-f]+)*",
            "device": r"/dev/[A-Za-z0-9][A-Za-z0-9_.+-]*",
        }.get(kernel["kind"])
        if (
            pattern is None
            or not isinstance(kernel["value"], str)
            or not re.fullmatch(pattern, kernel["value"])
        ):
            raise ValueError("invalid kernel root token")
    elif (
        kernel["status"] not in ("missing", "ambiguous", "unsupported", "unavailable")
        or kernel["kind"] is not None
        or kernel["value"] is not None
    ):
        raise ValueError("invalid unavailable kernel root")
    if value.get("root_backing") != root_backing(value["lsblk"], value["findmnt"]):
        raise ValueError("root backing differs from observed trees")
    if not isinstance(value.get("errors"), list) or any(
        e not in ("boot_clock_unavailable", "snapshot_output_limit") for e in value["errors"]
    ):
        raise ValueError("invalid observation errors")
    return value


def parse_lines(text):
    """Ignore untagged serial noise; never ignore a damaged tagged record."""
    found, previous = [], {}
    for line in text.splitlines():
        if PREFIX not in line:
            continue
        # A serial console may prepend one kernel line; require the JSON tail
        # to be complete and never try to salvage interleaved or truncated data.
        payload = line.split(PREFIX, 1)[1]
        if len((PREFIX + payload + "\n").encode("utf-8")) > MAX_ROW:
            raise ValueError("observer row exceeds limit")
        try:
            value = validate_snapshot(strict_json(payload))
        except (ValueError, TypeError, RecursionError) as exc:
            raise ValueError("malformed observer row") from exc
        older = previous.get(value["boot_id"])
        if older and (
            value["seq"] <= older["seq"]
            or value["uptime"] < older["uptime"]
            or any(
                value[key] != older[key]
                for key in ("observer_sha256", "fork_config_sha256", "identity_verifier")
            )
        ):
            raise ValueError("observer sequence or identity regressed")
        previous[value["boot_id"]] = value
        found.append(value)
    return found


def latest(text, *, boot_id=None, after_seq=None):
    """Return the newest record, refusing stale-boot or stale-sequence fallback.

    Consumers MUST inspect collector statuses. In particular, uid=None/absent
    is expected before the native installer creates the account, and an early
    bootc unavailable record cannot qualify the booted deployment.
    """
    values = parse_lines(text)
    if not values:
        raise ValueError("no observer evidence")
    value = values[-1]
    if boot_id is not None and value["boot_id"] != boot_id:
        raise ValueError("latest observer record is from another boot")
    if after_seq is not None and value["seq"] <= after_seq:
        raise ValueError("no fresh observer evidence")
    if value["errors"]:
        raise ValueError("latest observer record has collection errors")
    return value


def write_serial(fd, data, deadline):
    view = memoryview(data)
    end = min(deadline, time.monotonic() + 1)
    while view:
        remaining = end - time.monotonic()
        if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
            return False
        try:
            count = os.write(fd, view)
        except BlockingIOError:
            continue
        if count <= 0:
            return False
        view = view[count:]
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=MAX_DURATION)
    args = parser.parse_args(argv)
    if not 1 <= args.duration <= MAX_DURATION or os.geteuid() != 0:
        parser.error("requires root and a duration between 1 and 3600 seconds")
    deadline = time.monotonic() + args.duration
    try:
        fd = os.open("/dev/ttyS0", os.O_WRONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_NOFOLLOW)
        try:
            if not stat.S_ISCHR(os.fstat(fd).st_mode):
                return 2
            observer = Observer(deadline)
            seq, next_sample = 0, time.monotonic()
            while time.monotonic() < deadline:
                snapshot = observer.snapshot(seq)
                if not write_serial(fd, encode_snapshot(snapshot), deadline):
                    return 2
                seq += 1
                next_sample += INTERVAL
                now = time.monotonic()
                # Slow or unavailable collectors do not cause a catch-up flood.
                if next_sample < now:
                    next_sample = now + INTERVAL
                time.sleep(max(0, min(next_sample, deadline) - now))
        finally:
            os.close(fd)
    except (OSError, ValueError):
        return 2  # Never echo exception text, subprocess arguments, or environment.
    return 0


if __name__ == "__main__":
    sys.exit(main())
