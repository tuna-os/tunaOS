#!/usr/bin/env python3
"""A failed evidence step must not flip the draft release to public.

`!cancelled()` alone runs a step after earlier failures, so a failed
provenance upload or asset check could still reach `gh release edit
--draft=false`. The publish step must gate on `success()`.

Falsification: behavioural — put `!cancelled()` back in place of `success()`
in the publish step `if` and every test here fails.
"""

import re
from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "generate-changelog-release.yml"
)


def _steps():
    doc = yaml.safe_load(WORKFLOW.read_text())
    return doc["jobs"]["generate-release"]["steps"]


def _publish_index():
    steps = _steps()
    hits = [i for i, s in enumerate(steps) if "--draft=false" in s.get("run", "")]
    assert len(hits) == 1, "exactly one step must publish the draft"
    return hits[0]


def _conditions(cond):
    return [c.strip() for c in re.split(r"&&", cond)]


def test_publish_step_requires_success():
    cond = _steps()[_publish_index()]["if"]
    assert "success()" in _conditions(cond)


def test_publish_step_does_not_run_after_failure():
    cond = _steps()[_publish_index()]["if"]
    assert "always()" not in cond
    assert "failure()" not in cond
    # `!cancelled()` runs after a failed step; it is allowed only beside success().
    if "!cancelled()" in cond:
        assert "success()" in _conditions(cond)


def test_verification_steps_precede_publish():
    steps = _steps()
    names = [s.get("name", "") for s in steps]
    publish = _publish_index()
    assert names.index("Verify release assets") < publish
