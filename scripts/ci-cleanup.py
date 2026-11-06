#!/usr/bin/env python3
"""Job-scoped CI cleanup: remove what THIS job created, and nothing else.

`just ci-cleanup` runs this from an `if: always()` step. The rule is ownership
by run-scoped identity, never by pattern or age:

  scope = <GITHUB_RUN_ID>-<GITHUB_RUN_ATTEMPT>-<GITHUB_JOB>[-<CI_SCOPE_SUFFIX>]

A job owns an object only if the object carries that scope or the job
registered it in its own ledger:

  containers, pods, volumes, networks  labelled io.tunaos.ci.scope=<scope>
                                       (creators take the label from `labels`)
  images      registered with `own image NAME`; removed only while NAME still
              resolves to the image ID recorded at registration
  pidfile     registered with `own pidfile PATH` (QEMU, swtpm); the process is
              signalled only if its command line names that pidfile, so a
              reused PID is never touched
  loop        registered with `own loop FILE` (a file the job created); every
              loop device the kernel currently reports as backed by FILE is
              detached, so a device number reused by anyone else is untouched
  dir         registered with `own dir PATH`; a marker file with the scope is
              written inside, and the tree is removed only while that marker
              is present and matches
  scratch     `scratch` creates <state-root>/<scope>/scratch, always owned

What it never does: `podman system prune`, `podman image prune`, cache
deletion, or anything selected by name pattern. Nothing here can reach an
object created by another job, another attempt, or a developer's shell.

Exit status: 0 on success, including when there is nothing to clean and when
removing an owned object failed (a cleanup step must not fail the job). 1 only
when a ledger entry points at something that is NOT ours -- a directory
without our marker, a container carrying another scope -- which is refused and
reported rather than deleted.

Set DRY_RUN=1 to print what would be removed and remove nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LABEL_KEY = "io.tunaos.ci.scope"
MARKER = ".tunaos-ci-owned.json"
KINDS = ("image", "pidfile", "loop", "dir")
TERM_GRACE_SECONDS = 10


class Refusal(Exception):
    """A ledger entry names something this job does not own."""


def sanitize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def scope_id(env: dict[str, str] | None = None) -> str | None:
    """The job's identity, or None when we are not inside a CI job.

    Outside CI there is no scope and therefore nothing owned: a developer's
    machine is never cleaned by this script.
    """
    env = os.environ if env is None else env
    explicit = env.get("CI_SCOPE", "")
    if explicit:
        return sanitize(explicit) or None
    run_id = env.get("GITHUB_RUN_ID", "")
    if not run_id:
        return None
    parts = [run_id, env.get("GITHUB_RUN_ATTEMPT", "1") or "1", env.get("GITHUB_JOB", "job") or "job"]
    suffix = env.get("CI_SCOPE_SUFFIX", "")
    if suffix:
        parts.append(suffix)
    return sanitize("-".join(parts)) or None


def state_root(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    explicit = env.get("CI_STATE_ROOT", "")
    if explicit:
        return Path(explicit)
    runner_temp = env.get("RUNNER_TEMP", "")
    if runner_temp:
        return Path(runner_temp) / "tunaos-ci"
    return Path(tempfile.gettempdir()) / f"tunaos-ci-{os.getuid()}"


def scope_dir(scope: str) -> Path:
    return state_root() / scope


def allowed_roots() -> list[Path]:
    roots = [state_root(), Path(tempfile.gettempdir())]
    for name in ("RUNNER_TEMP", "GITHUB_WORKSPACE"):
        if os.environ.get(name):
            roots.append(Path(os.environ[name]))
    return [Path(os.path.realpath(r)) for r in roots]


def within_allowed_root(path: Path) -> bool:
    """True when `path` is strictly below an allowed root and is not itself one.

    RUNNER_TEMP and GITHUB_WORKSPACE usually sit under /tmp or /home, so being
    below *a* root is not enough: the roots themselves are refused outright.
    """
    real = Path(os.path.realpath(path.parent)) / path.name
    roots = allowed_roots()
    return real not in roots and any(root in real.parents for root in roots)


# --- ledger -----------------------------------------------------------------


def ledger_path(scope: str) -> Path:
    # One ledger per uid: a `sudo` build step (root) and the runner user both
    # register things for the same job, and neither can append to a file the
    # other created.
    return scope_dir(scope) / f"ledger-{os.geteuid()}.jsonl"


def ensure_scope_dir(scope: str) -> Path:
    directory = scope_dir(scope)
    for shared in (state_root(), directory):
        if not shared.is_dir():
            shared.parent.mkdir(parents=True, exist_ok=True)
            try:
                shared.mkdir(mode=0o1777)
            except FileExistsError:
                pass
            try:
                os.chmod(shared, 0o1777)  # sticky and umask-proof: root and the runner user both write here
            except PermissionError:
                pass
    marker = directory / MARKER
    if not marker.exists():
        write_marker(directory, scope)
    return directory


def write_marker(directory: Path, scope: str) -> None:
    payload = json.dumps({"schema": 1, "scope": scope, "run_id": os.environ.get("GITHUB_RUN_ID", "")})
    fd = os.open(directory / MARKER, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w") as handle:
        handle.write(payload + "\n")


def read_marker(directory: Path) -> dict | None:
    try:
        fd = os.open(directory / MARKER, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        with os.fdopen(fd) as handle:
            value = json.load(handle)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def owned_by(directory: Path, scope: str) -> bool:
    if directory.is_symlink() or not directory.is_dir():
        return False
    marker = read_marker(directory)
    return bool(marker) and marker.get("scope") == scope


def append_ledger(scope: str, record: dict) -> None:
    ensure_scope_dir(scope)
    line = json.dumps(record, sort_keys=True) + "\n"
    fd = os.open(ledger_path(scope), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def read_ledger(scope: str) -> list[dict]:
    """Every record this user or root registered; nobody else's ledger counts."""
    records = []
    for path in sorted(scope_dir(scope).glob("ledger-*.jsonl")):
        try:
            info = path.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in {os.geteuid(), 0}:
            continue
        for line in path.read_text().splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("kind") in KINDS:
                records.append(record)
    return records


# --- process / engine helpers ----------------------------------------------


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def sudo_usable() -> bool:
    if os.geteuid() == 0:
        return False
    if shutil.which("sudo") is None:
        return False
    return run(["sudo", "-n", "true"]).returncode == 0


def engines(root_too: bool = True) -> list[tuple[str, list[str]]]:
    """(name, argv prefix) for each podman storage this job may have used."""
    found: list[tuple[str, list[str]]] = []
    if shutil.which("podman"):
        found.append(("user", ["podman"]))
        if root_too and sudo_usable():
            found.append(("root", ["sudo", "-n", "podman"]))
    return found


def engine_prefix(name: str) -> list[str] | None:
    """argv prefix for the "user" or "root" podman storage, or None if unusable."""
    if not shutil.which("podman"):
        return None
    if name == "user" or os.geteuid() == 0:
        return ["podman"]  # already root: the one storage is both
    return ["sudo", "-n", "podman"] if sudo_usable() else None


def say(message: str) -> None:
    print(f"ci-cleanup: {message}", flush=True)


def dry_run() -> bool:
    return os.environ.get("DRY_RUN", "") in {"1", "true", "yes"}


def proc_start_time(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # comm may contain spaces/parens; fields after the last ')' are stable.
    fields = stat.rsplit(")", 1)[-1].split()
    return fields[19] if len(fields) > 19 else None


def proc_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


# --- registration -----------------------------------------------------------


def own(kind: str, value: str, root: bool) -> int:
    scope = scope_id()
    if scope is None:
        # Not in a job: nothing to own, and registering would invent a scope.
        return 0
    if kind == "dir":
        path = Path(value)
        if not path.is_absolute() or path.is_symlink() or not path.is_dir():
            say(f"refusing to register {value}: not an absolute, non-symlink directory")
            return 1
        if not within_allowed_root(path):
            say(f"refusing to register {value}: outside RUNNER_TEMP/GITHUB_WORKSPACE/tmp")
            return 1
        existing = read_marker(path)
        if existing is not None and existing.get("scope") != scope:
            say(f"refusing to register {value}: owned by scope {existing.get('scope')}")
            return 1
        write_marker(path, scope)
        append_ledger(scope, {"kind": "dir", "path": str(path)})
    elif kind == "pidfile":
        path = Path(value)
        if not path.is_absolute():
            say(f"refusing to register pidfile {value}: not absolute")
            return 1
        append_ledger(scope, {"kind": "pidfile", "path": str(path)})
    elif kind == "loop":
        # The value is the file this job created and attached loop devices to.
        path = Path(value)
        if not path.is_absolute() or path.is_symlink() or not within_allowed_root(path):
            say(f"refusing to register loop backing file {value}: not an absolute, non-symlink path under RUNNER_TEMP/GITHUB_WORKSPACE/tmp")
            return 1
        append_ledger(scope, {"kind": "loop", "backing": str(path)})
    elif kind == "image":
        name = "root" if (root or os.geteuid() == 0) else "user"
        prefix = engine_prefix(name)
        image_id = ""
        if prefix:
            result = run([*prefix, "image", "inspect", "--format", "{{.Id}}", value])
            image_id = result.stdout.strip() if result.returncode == 0 else ""
        if not image_id:
            say(f"refusing to register image {value}: not present in {name} storage")
            return 1
        append_ledger(scope, {"kind": "image", "name": value, "id": image_id, "engine": name})
    return 0


# --- cleanup ----------------------------------------------------------------


def stop_process(pid: int, start: str, root_ok: bool) -> None:
    def signal_pid(sig: int) -> None:
        if proc_start_time(pid) != start:
            return
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            if root_ok:
                run(["sudo", "-n", "kill", f"-{int(sig)}", str(pid)])

    signal_pid(signal.SIGTERM)
    deadline = time.monotonic() + TERM_GRACE_SECONDS
    while time.monotonic() < deadline and proc_start_time(pid) == start:
        time.sleep(0.2)
    signal_pid(signal.SIGKILL)


def clean_pidfile(record: dict) -> None:
    path = Path(record["path"])
    try:
        pid = int(path.read_text().strip().split()[0])
    except (OSError, ValueError, IndexError):
        return  # no pidfile, or never started: nothing of ours is running
    start = proc_start_time(pid)
    if start is None:
        return
    if str(path) not in proc_cmdline(pid):
        # The pid was recycled by a process that never heard of our pidfile.
        say(f"pid {pid} no longer belongs to {path}; leaving it alone")
        return
    if dry_run():
        say(f"[dry-run] would stop pid {pid} ({path})")
        return
    say(f"stopping pid {pid} ({path})")
    stop_process(pid, start, sudo_usable())


def clean_loop(record: dict) -> None:
    """Detach every loop device that currently backs the file this job created."""
    backing = record["backing"]
    result = run(["losetup", "--noheadings", "--output", "NAME", "-j", backing])
    attached = result.stdout.split() if result.returncode == 0 else []
    for dev in attached:
        if dry_run():
            say(f"[dry-run] would detach {dev} ({backing})")
            continue
        say(f"detaching {dev} ({backing})")
        if run(["losetup", "-d", dev]).returncode != 0 and not (sudo_usable() and run(["sudo", "-n", "losetup", "-d", dev]).returncode == 0):
            say(f"warning: could not detach {dev}")


def clean_image(record: dict) -> None:
    prefix = engine_prefix(record.get("engine", "user"))
    if not prefix:
        return
    result = run([*prefix, "image", "inspect", "--format", "{{.Id}}", record["name"]])
    if result.returncode != 0:
        return  # already gone
    if result.stdout.strip() != record["id"]:
        say(f"{record['name']} now names a different image; leaving it alone")
        return
    if dry_run():
        say(f"[dry-run] would remove image {record['name']}")
        return
    say(f"removing image {record['name']}")
    if run([*prefix, "rmi", record["name"]]).returncode != 0:
        say(f"warning: could not remove image {record['name']} (still in use?)")


def clean_dir(record: dict, scope: str) -> None:
    path = Path(record["path"])
    if not path.exists() and not path.is_symlink():
        return
    if not within_allowed_root(path):
        raise Refusal(f"{path} is outside the roots a job may own")
    if not owned_by(path, scope):
        raise Refusal(f"{path} does not carry this job's ownership marker")
    remove_tree(path)


def remove_tree(path: Path) -> None:
    if dry_run():
        say(f"[dry-run] would remove {path}")
        return
    say(f"removing {path}")
    shutil.rmtree(path, ignore_errors=True)
    if path.exists() and sudo_usable():
        # Root-owned files (sudo build steps) survive an unprivileged rmtree.
        run(["sudo", "-n", "rm", "-rf", "--one-file-system", "--", str(path)])
    if path.exists():
        say(f"warning: could not fully remove {path}")


LABEL_SWEEPS = (
    ("container", ["ps", "-a", "--filter"], ["--format", "{{.ID}}"], ["rm", "-f", "-t", "5"]),
    ("pod", ["pod", "ps", "--filter"], ["--format", "{{.ID}}"], ["pod", "rm", "-f", "-t", "5"]),
    ("volume", ["volume", "ls", "--filter"], ["--format", "{{.Name}}"], ["volume", "rm", "-f"]),
    ("network", ["network", "ls", "--filter"], ["--format", "{{.Name}}"], ["network", "rm", "-f"]),
)


def clean_labelled(scope: str) -> None:
    """Sweep objects that carry this job's scope label, in every storage."""
    label = f"label={LABEL_KEY}={scope}"
    for engine_name, prefix in engines():
        for kind, list_cmd, fmt, rm_cmd in LABEL_SWEEPS:
            listed = run([*prefix, *list_cmd, label, *fmt])
            if listed.returncode != 0:
                continue
            for ident in listed.stdout.split():
                if dry_run():
                    say(f"[dry-run] would remove {kind} {ident} ({engine_name})")
                    continue
                say(f"removing {kind} {ident} ({engine_name})")
                if run([*prefix, *rm_cmd, ident]).returncode != 0:
                    say(f"warning: could not remove {kind} {ident}")


def cleanup() -> int:
    scope = scope_id()
    if scope is None:
        say("not running inside a CI job (no GITHUB_RUN_ID/CI_SCOPE); nothing is owned, nothing to do")
        return 0
    say(f"scope {scope}")
    records = read_ledger(scope)
    refusals: list[str] = []

    # Order matters: stop the processes that hold devices and files first.
    for kind, handler in (("pidfile", clean_pidfile), ("loop", clean_loop)):
        for record in (r for r in records if r["kind"] == kind):
            handler(record)
    clean_labelled(scope)
    for record in (r for r in records if r["kind"] == "image"):
        clean_image(record)
    for record in reversed([r for r in records if r["kind"] == "dir"]):
        try:
            clean_dir(record, scope)
        except Refusal as exc:
            refusals.append(str(exc))

    directory = scope_dir(scope)
    if directory.exists() or directory.is_symlink():
        if within_allowed_root(directory) and owned_by(directory, scope):
            remove_tree(directory)
        else:
            refusals.append(f"{directory} does not carry this job's ownership marker")

    for message in refusals:
        say(f"REFUSED: {message}; not removed")
    return 1 if refusals else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="remove everything this job owns (default for `just ci-cleanup`)")
    sub.add_parser("scope", help="print this job's scope id (exit 1 outside CI)")
    sub.add_parser("labels", help="print `--label` arguments, one per line, for podman create/run/build")
    sub.add_parser("scratch", help="create and print this job's owned scratch directory")
    own_parser = sub.add_parser("own", help="register an object this job created")
    own_parser.add_argument("kind", choices=KINDS)
    own_parser.add_argument("value")
    own_parser.add_argument("--root", action="store_true", help="image lives in root (sudo) podman storage")
    args = parser.parse_args(argv)

    if args.command == "run":
        return cleanup()
    scope = scope_id()
    if args.command == "scope":
        if scope is None:
            return 1
        print(scope)
        return 0
    if args.command == "labels":
        if scope is not None:
            print("--label")
            print(f"{LABEL_KEY}={scope}")
        return 0
    if args.command == "scratch":
        if scope is None:
            return 1
        path = ensure_scope_dir(scope) / "scratch"
        path.mkdir(exist_ok=True, mode=0o755)
        print(path)
        return 0
    return own(args.kind, args.value, args.root)


if __name__ == "__main__":
    sys.exit(main())
