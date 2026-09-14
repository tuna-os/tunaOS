"""GitHub transport adapter for the matrix-status generator.

Keep process execution, JSON decoding, and retry policy at this boundary so
the status-domain code does not need to know how GitHub data is acquired.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from typing import Any, Protocol


class CompletedProcess(Protocol):
    """The part of subprocess.CompletedProcess used by this adapter."""

    stdout: str


RunCommand = Callable[..., CompletedProcess]
Sleep = Callable[[float], Any]


def query_json(
    args: Sequence[str],
    *,
    run: RunCommand = subprocess.run,
    sleep: Sleep,
    attempts: int = 3,
):
    """Run ``gh`` and decode its JSON response, retrying expected failures.

    ``run`` and ``sleep`` are injected to keep this adapter independently
    testable and to let the executable retain its established test seam.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be at least 1, got {attempts}")

    for attempt in range(attempts):
        try:
            out = run(
                ["gh", *args], capture_output=True, text=True, check=True
            ).stdout
            return json.loads(out) if out.strip() else None
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            if attempt + 1 == attempts:
                return None
            sleep(2)
    return None
