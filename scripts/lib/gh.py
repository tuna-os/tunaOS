"""Shared `gh` CLI subprocess wrapper for scripts/*.py.

Consolidates four independently-hardened wrappers
(import-frontend-parity.py, rerun-startup-failures.py, gen-matrix-status.py,
detect-dead-gates.py) that each rediscovered part of the same lesson: a
`gh` call that fails silently or drops stderr turns into an incident that
looks like "no data" instead of "the query failed." See
tuna-os/tunaOS#2716.

Two layers, matching the two ways the four original call sites actually used
their wrappers:

  * `run(args)` -- never raises, never retries. Returns a CompletedProcess
    (or a `_Failed` stand-in shaped like one if `gh` itself is missing from
    PATH). For callers that inspect `.returncode`/`.stdout`/`.stderr`
    themselves and degrade gracefully by design (a fetch that reports one
    frontend as "unfetched" rather than aborting the whole import; a
    best-effort log fetch that skips an unreadable run).

  * `gh(args, retries=1, backoff=2.0)` / `gh_json(...)` -- raises `GhError`
    (with full stdout+stderr) after retries are exhausted. For callers
    where a failed query must not be silently read as "empty" or "no
    runs" -- the actual defect a 2026-09-24 incident traced to `gen_json(...)
    or []` (tuna-os/tunaOS#2716).

Usage:
    from lib.gh import run, gh, gh_json, GhError

    r = run(["run", "list", "--limit", "10"])           # never raises
    out = gh(["run", "list", "--limit", "10"])          # raises GhError
    data = gh_json(["run", "list", "--json", "..."])    # raises GhError; None on empty output
    data = gh_json(["run", "list", "--json", "..."], retries=3)
"""
from __future__ import annotations

import json
import subprocess
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


def gh_json(args: list[str], retries: int = 1, backoff: float = 2.0):
    """gh() plus JSON parsing. Returns None for genuinely empty output.

    Raises GhError on failure after retries are exhausted -- callers that
    need to distinguish "no runs" (empty output) from "the query failed"
    should catch GhError explicitly rather than writing
    `gh_json(...) or []`, which conflates the two (see tuna-os/tunaOS#2716,
    citing the 2026-09-24 incident where exactly that conflation scored a
    healthy workflow's cells as untested).
    """
    out = gh(args, retries=retries, backoff=backoff)
    return json.loads(out) if out.strip() else None
