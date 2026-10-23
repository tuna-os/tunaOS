#!/usr/bin/env python3
"""Record sanitized package requests without retaining command output or secrets."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import uuid

READ_ONLY = {
    "dnf": {"repoquery", "list", "info", "search", "check", "clean", "makecache", "repolist"},
    "apt": {"update", "clean", "autoclean", "list", "show", "search", "policy"},
    "zypper": {"refresh", "clean", "repos", "lr", "search", "se", "info"},
}
OPERATIONS = {
    "dnf": {"install", "remove", "upgrade", "update", "downgrade", "reinstall", "swap", "distro-sync", "group", "groupinstall", "autoremove", "builddep", "config-manager", "copr", "versionlock", "history"},
    "apt": {"install", "remove", "purge", "autoremove", "upgrade", "dist-upgrade", "full-upgrade", "build-dep"},
    "zypper": {"install", "in", "remove", "rm", "update", "up", "dup", "patch", "addrepo", "ar", "removerepo", "rr", "modifyrepo", "mr"},
}
FLAGS = {"-y", "--assumeyes", "--noconfirm", "--needed", "--non-interactive", "--no-recommends", "--no-install-recommends", "--allowerasing", "--nobest", "--best", "--skip-unavailable", "--skip-broken", "--refresh", "-qq", "-q", "--verbose", "--getbinpkg", "--quiet", "--force-confdef", "--force-confold", "--gpg-auto-import-keys"}
SAFE_EXPRESSION = re.compile(r"[A-Za-z0-9@+_.:*?!<>=~^%/-]+\Z")
SAFE_REPO = re.compile(r"[A-Za-z0-9_.:*,-]+\Z")
SETOPTS = {"install_weak_deps", "keepcache", "tsflags", "skip_if_unavailable", "gpgcheck", "repo_gpgcheck", "best", "timeout", "retries", "exclude", "module_platform_id"}


def normalize(manager: str, arguments: list[str]) -> dict | None:
    """Recognize requests conservatively; unsupported inputs remain coverage gaps."""
    canonical = {"dnf5": "dnf", "apt-get": "apt", "emerge": "portage"}.get(manager, manager)
    args = list(arguments)
    operation = None
    requests: list[str] = []
    gaps: set[str] = set()
    options: list[str] = []
    if canonical == "pacman":
        flag = next((a for a in args if a.startswith("-") and not a.startswith("--")), "")
        if flag.startswith(("-Q", "-F")) or (flag.startswith("-S") and any(c in flag[2:] for c in "islgp")):
            return None
        operation = "install" if flag.startswith(("-S", "-U")) else "remove" if flag.startswith("-R") else "unknown"
        if flag in args:
            args.remove(flag)
        options.append(flag)
    elif canonical == "rpm":
        if any(a in {"--eval", "--showrc", "--version", "--help"} for a in args):
            return None
        flags = [a for a in args if a.startswith("-")]
        if any(a.startswith("-q") or a == "--query" for a in flags):
            return None
        operation = "remove" if any(a == "--erase" or a.startswith("-e") for a in flags) else "install" if any(a in {"--install", "--upgrade", "--freshen"} or re.fullmatch(r"-[iUF][vh]*", a) for a in flags) else "unknown"
        if any(a not in {"--erase", "--install", "--upgrade", "--freshen"} and not re.fullmatch(r"-[iUFe][vh]*", a) for a in flags):
            gaps.add("unsupported-manager-option")
            args = []
        else:
            args = [a for a in args if a not in flags]
        gaps.add("local-artifact-provenance-required")
    elif canonical == "dpkg":
        if any(a in {"--list", "-l", "--status", "-s", "--print-architecture", "--compare-versions"} for a in args):
            return None
        operation = "remove" if any(a in {"-r", "-P", "--remove", "--purge"} for a in args) else "configure" if "--configure" in args else "install" if any(a in {"-i", "--install", "--unpack"} for a in args) else "unknown"
        if any(a.startswith("-") and a not in {"-r", "-P", "--remove", "--purge", "--configure", "-i", "--install", "--unpack"} for a in args):
            gaps.add("unsupported-manager-option")
            args = []
        else:
            args = [a for a in args if not a.startswith("-")]
        gaps.add("local-artifact-provenance-required")
    elif canonical == "portage":
        if any(a in {"--sync", "--info", "--search", "-s", "--version"} for a in args):
            return None
        operation = "remove" if any(a in {"--unmerge", "--deselect", "-C"} for a in args) else "install"
    else:
        for index, arg in enumerate(args):
            if arg in READ_ONLY.get(canonical, set()):
                return None
            if arg in OPERATIONS.get(canonical, set()):
                operation = arg
                args = args[:index] + args[index + 1:]
                break
        if operation is None and any(a in {"--version", "--help", "-h"} for a in args):
            return None
    if operation is None or operation == "unknown":
        gaps.add("unknown-manager-operation")
        args = []  # An unknown option's value might be a secret.
        operation = "unknown"
    if operation in {"copr", "config-manager", "versionlock", "history", "addrepo", "ar", "removerepo", "rr", "modifyrepo", "mr"}:
        gaps.add("native-source-or-policy-operation-required")
        args = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg in FLAGS or (canonical == "portage" and arg in {"--unmerge", "--deselect", "-C", "--update", "--deep", "--newuse", "--oneshot"}):
            options.append(arg)
            continue
        if arg.startswith("--setopt="):
            key, _, value = arg[len("--setopt="):].partition("=")
            if key not in SETOPTS or not SAFE_REPO.fullmatch(value):
                gaps.add("unsupported-manager-option")
                break
            else:
                options.append("--setopt=" + key + "=" + value)
            continue
        if arg.startswith(("--enablerepo=", "--disablerepo=", "--exclude=")):
            value = arg.split("=", 1)[1]
            if SAFE_REPO.fullmatch(value):
                options.append(arg)
            else:
                gaps.add("unsupported-manager-option")
                break
            continue
        if arg.startswith("-"):
            gaps.add("unsupported-manager-option")
            # Do not persist following operands when their semantics are unknown.
            break
        if "://" in arg or arg.startswith(("/", "./", "../")) or arg.endswith((".rpm", ".deb", ".pkg.tar.zst", ".pkg.tar.xz")):
            gaps.add("local-or-remote-artifact-provenance-required")
            continue
        if not SAFE_EXPRESSION.fullmatch(arg):
            gaps.add("unsupported-package-expression")
            continue
        requests.append(arg)
    if operation in {"group", "groupinstall"}:
        gaps.add("native-group-expansion-required")
    return {"manager": canonical, "operation": operation, "requests": requests, "options": options, "coverageGaps": sorted(gaps)}


def append(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    begin = commands.add_parser("start")
    begin.add_argument("--manager", required=True)
    begin.add_argument("--origin", required=True)
    begin.add_argument("--line", type=int, required=True)
    begin.add_argument("arguments", nargs=argparse.REMAINDER)
    finish = commands.add_parser("finish")
    finish.add_argument("--request-id", required=True)
    finish.add_argument("--exit-code", type=int, required=True)
    args = parser.parse_args()
    if args.command == "finish":
        if not re.fullmatch(r"[0-9a-f]{32}", args.request_id) or not 0 <= args.exit_code <= 255:
            raise ValueError("invalid package request result")
        append(args.ledger, {"schemaVersion": 1, "kind": "package-result", "requestId": args.request_id, "finishedAt": timestamp(), "exitCode": args.exit_code})
        return 0
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    normalized = normalize(args.manager, arguments)
    if normalized is None:
        return 0
    scope = os.environ.get("TUNAOS_PACKAGE_SCOPE", "final")
    if scope not in {"final", "transient"}:
        raise ValueError("package scope must be final or transient")
    required_value = os.environ.get("TUNAOS_PACKAGE_REQUIRED", "true")
    if required_value not in {"true", "false"}:
        raise ValueError("package requiredness must be true or false")
    target = None
    raw_target = os.environ.get("TUNAOS_CONTRACT_TARGET")
    if raw_target:
        target = json.loads(raw_target)
        if not isinstance(target, dict) or set(target) != {"variant", "flavor", "platform", "cpuBaseline", "hardwareScope"}:
            raise ValueError("invalid contract target")
    else:
        normalized["coverageGaps"].append("missing-contract-target")
    origin = args.origin
    prefix = os.environ.get("CONTEXT_PATH", "/run/context").rstrip("/") + "/"
    if origin.startswith(prefix):
        origin = origin[len(prefix):]
    elif origin.startswith("/"):
        origin = "<external>"
        normalized["coverageGaps"].append("external-request-origin")
    request_id = uuid.uuid4().hex
    phase = os.environ.get("TUNAOS_PACKAGE_PHASE", "unclassified")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", phase):
        raise ValueError("invalid package phase")
    if phase == "unclassified":
        normalized["coverageGaps"].append("missing-package-phase")
    append(args.ledger, {"schemaVersion": 1, "kind": "package-request", "requestId": request_id, "target": target, "phase": phase, "scope": scope, "required": required_value == "true", "origin": {"path": origin, "line": args.line}, "startedAt": timestamp(), **normalized})
    print(request_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
