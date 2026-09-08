"""The dead-gate detector must detect, and must not over-claim.

Epic #2250's CI contract catches a criterion with no executing implementation
-- the always-GREEN case. This detector covers the inverse: an assertion that
is red in every run. On this repo the inverse cost more, because three
assertions in e2e-runtime-checks.sh sat red on every cell for months and were
read as known issues rather than as gates measuring nothing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "detect-dead-gates.py"

sys.path.insert(0, str(ROOT / "scripts"))


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _log(tmp_path: Path, name: str, lines: list[str]) -> str:
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_an_always_red_assertion_is_reported(tmp_path: Path) -> None:
    logs = [
        _log(tmp_path, f"r{i}.log", [
            "ok 1 - the good one",
            "not ok 2 - the always red one",
        ])
        for i in range(3)
    ]
    out = _run("--from-logs", *logs).stdout
    assert "the always red one" in out
    assert "the good one" not in out


def test_an_assertion_that_ever_passes_is_not_reported(tmp_path: Path) -> None:
    """One green run is enough to prove the assertion can pass."""
    logs = [
        _log(tmp_path, "r0.log", ["not ok 1 - flaky"]),
        _log(tmp_path, "r1.log", ["not ok 1 - flaky"]),
        _log(tmp_path, "r2.log", ["ok 1 - flaky"]),
    ]
    out = _run("--from-logs", *logs).stdout
    assert "No assertion was red in every run" in out


def test_it_refuses_to_judge_on_too_little_evidence(tmp_path: Path) -> None:
    """Two runs is not a pattern; saying so is better than a confident wrong answer."""
    logs = [_log(tmp_path, "r0.log", ["not ok 1 - only twice"])]
    r = _run("--from-logs", *logs)
    assert "not enough evidence" in r.stderr
    assert r.returncode == 0


def test_serial_console_prefixes_are_parsed(tmp_path: Path) -> None:
    """The real source is a guest serial log, where TAP carries a timestamp."""
    logs = [
        _log(tmp_path, f"r{i}.log", [
            "[   11.6] e2e-runtime-checks[943]: not ok - graphical.target is active",
        ])
        for i in range(3)
    ]
    out = _run("--from-logs", *logs).stdout
    assert "graphical.target is active" in out


def test_measured_values_do_not_split_one_assertion_into_many(tmp_path: Path) -> None:
    """`(state=activating)` varies per run; the assertion is still one assertion."""
    logs = [
        _log(tmp_path, "r0.log", ["not ok - graphical.target is active (state=inactive)"]),
        _log(tmp_path, "r1.log", ["not ok - graphical.target is active (state=activating)"]),
        _log(tmp_path, "r2.log", ["not ok - graphical.target is active (state=inactive)"]),
    ]
    out = _run("--from-logs", *logs).stdout
    # Count the CANDIDATE LINES, not the whole output -- the explanatory text
    # below the list cites this same assertion by name as its worked example.
    listed = [l for l in out.splitlines() if l.strip().startswith("not ok (always) -")]
    assert len(listed) == 1, listed


def test_it_names_both_readings_rather_than_prejudging(tmp_path: Path) -> None:
    """An always-red assertion may be a dead gate OR a real persistent failure.

    Verified example of each here: `graphical.target is active` was a dead
    gate; the pantheon `screen is not blank` assertions were a live session
    that genuinely never painted. Reporting only the first would have sent
    someone to 'fix the test' on a real bug.
    """
    logs = [_log(tmp_path, f"r{i}.log", ["not ok - something"]) for i in range(3)]
    out = _run("--from-logs", *logs).stdout
    assert "DEAD GATE" in out
    assert "REAL and persistent failure" in out
