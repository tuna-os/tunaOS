#!/usr/bin/env python3
"""Read-only, partial native ownership evidence from executed contract checks.

This report never admits a package removal. It records selected file roots,
not their dependency closure or every resource required by a working desktop.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

KINDS = {"command", "glob", "unit", "user_unit", "waiver"}
MAX_BYTES = 1024 * 1024
MAX_CHECKS = 256
MAX_PATHS = 512
QUERY_DEADLINE = None
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9+_.-]*")
DEB_SELECTOR = re.compile(r"([a-z0-9][a-z0-9+.-]*)(?::([a-z0-9][a-z0-9-]*))?")


class EvidenceError(ValueError):
    pass


def query(args):
    """Keep nonzero status and diagnostics; never pipe away a native failure."""
    try:
        remaining = 15 if QUERY_DEADLINE is None else min(15, QUERY_DEADLINE - time.monotonic())
        if remaining <= 0:
            raise EvidenceError("native query time budget exhausted")
        result = subprocess.run(args, capture_output=True, text=True, timeout=remaining,
                                env={**os.environ, "LC_ALL": "C"})
        if len(result.stdout) + len(result.stderr) > MAX_BYTES:
            raise EvidenceError("native query output exceeded the limit")
        return result
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError(f"native query unavailable: {exc}") from exc


def parse_packages(output, manager):
    records = []
    for line in output.splitlines():
        fields = line.split("\t")
        if manager == "apt":
            if len(fields) != 4 or fields.pop() != "installed":
                raise EvidenceError("owner is not in an installed dpkg state")
        if len(fields) != 3:
            raise EvidenceError("malformed native owner record")
        name, version, arch = fields
        if not NAME.fullmatch(name) or not version or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in version):
            raise EvidenceError("invalid native owner identity")
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", arch):
            raise EvidenceError("invalid native owner architecture")
        records.append({"name": name, "version": version, "architecture": arch})
    if not records:
        raise EvidenceError("empty native owner result")
    return sorted(records, key=lambda item: tuple(item.values()))


def native_owners(manager, path):
    if manager == "dnf":
        result = query(["rpm", "-qf", "--qf", "%{NAME}\\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\\t%{ARCH}\\n", "--", path])
        if result.returncode == 1 and result.stdout.strip() == f"file {path} is not owned by any package" and not result.stderr.strip():
            return {"ownership_status": "unowned", "owners": []}
        if result.returncode != 0:
            raise EvidenceError(f"rpm owner query exited {result.returncode}: {result.stderr.strip() or result.stdout.strip()}")
        return {"ownership_status": "owned", "owners": parse_packages(result.stdout, manager)}
    result = query(["dpkg-query", "--search", "--", path])
    if result.returncode == 1 and not result.stdout and result.stderr.strip() == f"dpkg-query: no path found matching pattern {path}":
        return {"ownership_status": "unowned", "owners": []}
    if result.returncode != 0:
        raise EvidenceError(f"dpkg owner query exited {result.returncode}: {result.stderr.strip()}")
    selectors = set()
    for line in result.stdout.splitlines():
        owner, separator, matched_path = line.partition(": ")
        if not separator or matched_path != path:
            raise EvidenceError("ambiguous dpkg search result (including diversions)")
        for selector in owner.split(", "):
            if not DEB_SELECTOR.fullmatch(selector):
                raise EvidenceError("invalid dpkg owner selector")
            selectors.add(selector)
    if not selectors:
        raise EvidenceError("empty dpkg owner search result")
    records = []
    for selector in sorted(selectors):
        result = query(["dpkg-query", "--show", "--showformat=${Package}\\t${Version}\\t${Architecture}\\t${db:Status-Status}\\n", "--", selector])
        if result.returncode != 0:
            raise EvidenceError(f"dpkg installed owner query exited {result.returncode}: {result.stderr.strip()}")
        owned = parse_packages(result.stdout, manager)
        expected = DEB_SELECTOR.fullmatch(selector)
        if len(owned) != 1 or owned[0]["name"] != expected[1] or (expected[2] and owned[0]["architecture"] != expected[2]):
            raise EvidenceError("dpkg owner selector resolved to a different identity")
        records.extend(owned)
    return {"ownership_status": "owned", "owners": records}


def observe_path(manager, path):
    record = {"path": path, "owners": []}
    if not path.startswith("/") or any(ord(c) < 32 or ord(c) == 127 or c in "*?[]\\" for c in path):
        return {**record, "ownership_status": "unresolved", "reason": "path is not an unambiguous absolute filename"}
    target = Path(path)
    if not target.exists():
        return {**record, "ownership_status": "unresolved", "reason": "selected path is missing or a dangling symlink"}
    if not target.is_file():
        return {**record, "ownership_status": "unresolved", "reason": "selected path is not a regular file; directories are not expanded"}
    try:
        return {**record, **native_owners(manager, path)}
    except EvidenceError as exc:
        return {**record, "ownership_status": "query_failed", "reason": str(exc)[:2048]}


def unit_paths(kind, selector):
    """Resolve the first installed candidate in systemd's own load-path order."""
    if not re.fullmatch(r"[A-Za-z0-9_.@:-]+", selector):
        raise EvidenceError("invalid selected unit name")
    result = query(["systemd-analyze", "--user" if kind == "user_unit" else "--system", "unit-paths"])
    if result.returncode != 0:
        raise EvidenceError(f"systemd unit-path query exited {result.returncode}: {result.stderr.strip()}")
    directories = result.stdout.splitlines()
    if not directories or len(directories) > 128 or any(not p.startswith("/") for p in directories):
        raise EvidenceError("systemd returned invalid unit load directories")
    for directory in directories:
        candidate = Path(directory) / (selector + ".service")
        if candidate.exists() or candidate.is_symlink():
            return [str(candidate)]
    raise EvidenceError("passed unit listing has no file in systemd's reported load paths")


def read_events(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or not raw or not raw.endswith(b"\0"):
        raise EvidenceError("empty, oversized or incomplete check event stream")
    fields = raw[:-1].decode("utf-8").split("\0")
    events = []
    offset = 0
    total_paths = 0
    while offset < len(fields):
        if offset + 4 > len(fields):
            raise EvidenceError("truncated check event")
        kind, selector, line, count = fields[offset:offset + 4]
        if kind not in KINDS or not line.isdigit() or not count.isdigit():
            raise EvidenceError("invalid check event header")
        count = int(count)
        total_paths += count
        if count > MAX_PATHS or total_paths > MAX_PATHS or offset + 4 + count > len(fields):
            raise EvidenceError("truncated or oversized check path list")
        events.append({"kind": kind, "selector": selector, "source_line": int(line),
                       "selected_paths": fields[offset + 4:offset + 4 + count]})
        offset += 4 + count
        if len(events) > MAX_CHECKS:
            raise EvidenceError("too many check events")
    return events


def report(events, manager, desktop, exit_code, completed, waived, source):
    observations = []
    for event in events:
        observation = {k: v for k, v in event.items() if k != "selected_paths"}
        observation["check_status"] = "waived" if event["kind"] == "waiver" else "passed"
        paths = event["selected_paths"]
        if event["kind"] in {"unit", "user_unit"}:
            try:
                paths = unit_paths(event["kind"], event["selector"])
            except EvidenceError as exc:
                observation["resolution_error"] = str(exc)[:2048]
        expanded = []
        for path in paths:
            if path not in expanded:
                expanded.append(path)
            if Path(path).is_absolute():
                try:
                    resolved = str(Path(path).resolve(strict=True))
                    if resolved not in expanded:
                        expanded.append(resolved)
                except (OSError, RuntimeError):
                    pass
        observation["paths"] = [observe_path(manager, path) for path in expanded]
        if not expanded and event["kind"] != "waiver":
            observation.setdefault("resolution_error", "successful check did not yield an absolute file path")
        observations.append(observation)
    status = "failed" if exit_code else "incomplete" if not completed else "waived" if waived else "passed"
    owners = {tuple(item[key] for key in ("name", "version", "architecture"))
              for obs in observations for path in obs["paths"] for item in path["owners"]}
    return {
        "schema_version": 1,
        "purpose": "partial-contract-native-owner-evidence",
        "authorizes_removal": False,
        "desktop": desktop,
        "package_manager": manager,
        "sources": {"contract_sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                    "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "hook_sha256": hashlib.sha256(Path(__file__).with_suffix(".sh").read_bytes()).hexdigest()},
        "contract": {"status": status, "exit_code": exit_code, "completed": completed,
                     "waived_requirements": waived},
        "coverage": {"complete": False,
                     "scope": "selected roots from executed require_command, require_glob, require_any_glob, require_unit, require_any_unit, require_user_unit and require_any_user_unit checks",
                     "excludes": ["native dependency closure", "unit ExecStart and dependency graphs", "files inside matched directories", "GNOME schema and version checks", "codec execution and configuration checks", "dconf, Flatpak, branding and greeter content checks", "conditional checks not reached", "runtime, boot and installer behavior"]},
        "observations": observations,
        "observed_owner_packages": [dict(zip(("name", "version", "architecture"), item)) for item in sorted(owners)],
    }


def checked_output(path):
    target = Path(path).absolute()
    if any(item.is_symlink() for item in (target, *target.parents)):
        raise EvidenceError("evidence output cannot contain symlinks")
    if target.exists() or not target.parent.is_dir():
        raise EvidenceError("evidence output must be new with an existing parent")
    return target


def main():
    global QUERY_DEADLINE
    QUERY_DEADLINE = time.monotonic() + 60
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--events")
    parser.add_argument("--manager", choices=("apt", "dnf"), required=True)
    parser.add_argument("--desktop", choices=("gnome", "xfce"), required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--completed", choices=("0", "1"), default="0")
    parser.add_argument("--waived", type=int, default=0)
    parser.add_argument("--validate-output", action="store_true")
    args = parser.parse_args()
    try:
        output = checked_output(args.output)
        if args.validate_output:
            return 0
        if not args.events or args.exit_code < 0 or args.waived < 0:
            raise EvidenceError("events and valid contract status are required")
        events = read_events(args.events) if Path(args.events).stat().st_size else []
        if args.exit_code == 0 and args.completed == "1" and not events:
            raise EvidenceError("completed contract emitted no check evidence")
        value = report(events, args.manager, args.desktop, args.exit_code,
                       args.completed == "1", args.waived, args.source)
        data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        return 0
    except (EvidenceError, OSError, UnicodeError) as exc:
        print(f"contract owner evidence failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
