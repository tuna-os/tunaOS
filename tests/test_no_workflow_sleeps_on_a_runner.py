"""A workflow must not wait out a delay by sleeping on a hosted runner.

`rerun-infra-failures.yml` used to run `sleep 2700` inside the classifier job:
41 runs a week, 45 minutes each, of a runner that did nothing, on an org pool
that saturates (the merge queue sat idle for twelve hours behind it). A job
that waits on an environment's wait timer holds no runner, so the delay lives
there instead.

Falsification: structural. Putting `sleep 2700` back in any `run:` step, or
removing `environment:` from the `rerun` job, fails these tests.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# Retry backoffs are seconds to a few minutes. Five minutes of idle runner is
# the line between "backing off" and "waiting for something else to happen".
LONG_SLEEP_SECONDS = 300
LITERAL_SLEEP = re.compile(r"(?m)^[ \t]*(?:[^#\n]*[;&|][ \t]*)?sleep[ \t]+(\d+)[smh]?\b")


def _seconds(text: str, number: str) -> int:
    unit = re.search(rf"sleep[ \t]+{number}([smh]?)", text).group(1)
    return int(number) * {"": 1, "s": 1, "m": 60, "h": 3600}[unit]


def test_no_workflow_step_sleeps_for_five_minutes_or_more():
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in (job or {}).get("steps") or []:
                body = step.get("run")
                if not isinstance(body, str):
                    continue
                for match in LITERAL_SLEEP.finditer(body):
                    if _seconds(match.group(0), match.group(1)) >= LONG_SLEEP_SECONDS:
                        offenders.append(f"{path.name}:{job_name}: {match.group(0).strip()}")
    assert not offenders, (
        "a step sleeps on a runner; use an environment wait timer or a "
        "scheduled re-check instead: " + "; ".join(offenders)
    )


def test_the_infra_rerun_waits_on_an_environment_not_a_runner():
    doc = yaml.safe_load((WORKFLOWS / "rerun-infra-failures.yml").read_text(encoding="utf-8"))
    rerun = doc["jobs"]["rerun"]
    assert "infra-retry-wait" in str(rerun["environment"]), (
        "the re-run job no longer names the environment that carries the "
        "45 minute wait timer"
    )
    assert rerun["needs"] == "classify-and-rerun"
