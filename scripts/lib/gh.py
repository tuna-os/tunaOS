"""Shared `gh` CLI subprocess wrapper for scripts/*.py.

Replaces the independently-hardened wrappers in import-frontend-parity.py,
rerun-startup-failures.py, detect-dead-gates.py and gen-matrix-status.py,
which each rediscovered part of the same lesson: a `gh` call that fails
silently or drops stderr turns into an incident that looks like "no data"
instead of "the query failed." See tuna-os/tunaOS#2716.

Three layers, matching the three ways those call sites use `gh`:

  * `run(args)` -- never raises, never retries. Returns a CompletedProcess
    (or a `_Failed` stand-in shaped like one if `gh` itself is missing from
    PATH). For callers that inspect `.returncode`/`.stdout`/`.stderr`
    themselves and degrade gracefully by design (a fetch that reports one
    frontend as "unfetched" rather than aborting the whole import; a
    best-effort log fetch that skips an unreadable run).

  * `gh(args, retries=1, backoff=2.0)` -- raises `GhError` (with full
    stdout+stderr) after retries are exhausted. For callers where a failed
    query must not be silently read as "empty" or "no runs".

  * `gh_json(args, retries=3, backoff=2.0)` -- parses stdout as JSON,
    returning None (with a stderr warning naming the call and gh's reason)
    when the query fails after retries, or when stdout is empty. For
    callers that degrade a failed query to "unknown" by design; callers
    that must not read failure as "no data" raise on None themselves
    (see gen-matrix-status.py's `gh_json_required`).

Usage:
    from lib.gh import run, gh, gh_json, GhError

    r = run(["run", "list", "--limit", "10"])           # never raises
    out = gh(["run", "list", "--limit", "10"])          # raises GhError
    data = gh_json(["run", "view", "123", "--json", "jobs"])  # None on failure
"""
from __future__ import annotations

import json
import subprocess
import sys
import time


class GhError(RuntimeError):
    """A `gh` invocation that failed, carrying what `gh` actually said.

    Always includes both stdout and stderr in the message -- a bare
    CalledProcessError with capture_output=True drops the diagnostic line
    that explains the failure (see rerun-startup-failures.py's original
    incident, tuna-os/tunaOS#1933).
    """


class _Failed:
    """A `gh` invocation that could not even start, shaped like
    CompletedProcess so callers of `run()` need no special case."""

    returncode, stdout, stderr = 1, "", "gh CLI not found on PATH"


def run(args: list[str]) -> subprocess.CompletedProcess | _Failed:
    """Run `gh` once, never raising. Caller inspects .returncode/.stdout/.stderr."""
    try:
        return subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return _Failed()


def gh(args: list[str], retries: int = 1, backoff: float = 2.0) -> str:
    """Run `gh`, return stdout, raise GhError (with full stdout+stderr) on
    failure after `retries` attempts (default 1 = no retry), waiting
    `backoff` seconds between attempts.
    """
    last: subprocess.CompletedProcess | _Failed | None = None
    for attempt in range(retries):
        proc = run(args)
        if proc.returncode == 0:
            return proc.stdout
        last = proc
        if attempt < retries - 1:
            time.sleep(backoff)
    assert last is not None
    raise GhError(
        f"gh {' '.join(args)} exited {last.returncode}\n"
        f"  stdout: {last.stdout.strip() or '(empty)'}\n"
        f"  stderr: {last.stderr.strip() or '(empty)'}"
    )


def gh_json(args: list[str], retries: int = 3, backoff: float = 2.0):
    """Run `gh`, parse stdout as JSON. Returns None on missing/failed query.

    On success returns the parsed value (or None for empty stdout, exactly
    like a query with nothing to report). After `retries` failed attempts
    (nonzero exit or unparseable stdout) prints a warning naming the call
    and gh's own reason -- the job log of the 2026-09-24 refresh (run
    35990117734) that blanked every bonito cell carried no line at all
    about which call failed -- and returns None.
    """
    for attempt in range(retries):
        proc = run(args)
        detail: str | None = None
        if proc.returncode == 0:
            try:
                return json.loads(proc.stdout) if proc.stdout.strip() else None
            except json.JSONDecodeError as err:
                detail = str(err)
        else:
            # A `gh` that cannot even start (missing binary) arrives here as
            # the `_Failed` stand-in instead of raising FileNotFoundError.
            detail = proc.stderr
        if attempt == retries - 1:
            print(
                f"warning: gh {' '.join(args)}: {(detail or '').strip()}",
                file=sys.stderr,
            )
            return None
        time.sleep(backoff)
    return None
