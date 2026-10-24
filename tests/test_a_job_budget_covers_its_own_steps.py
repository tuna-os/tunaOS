"""A job's timeout must be able to cover the steps inside it.

`timeout-minutes` at the job level and at the step level are independent
budgets, and GitHub enforces both. When the job's is the smaller one the
steps never get to fail on their own terms: the job is cancelled with
every step still inside its limit, and `cancelled` is the same word
Actions uses for a spot reclamation or a user hitting the button. A real
failure and an infrastructure flake become indistinguishable.

That is not hypothetical. `iso-e2e.yml` carried a flat `timeout-minutes: 30`
while its build step declared 60 and its readiness step 20, so every
`source: build` cell died at exactly 30 minutes -- E2E guppy:xfce (job
97638529947) started building at 00:18:40 and was cancelled at 00:48:29.
A six-cell sweep produced no verdict about any cell it ran.

The check is deliberately weak in one direction: a job timeout written as
an expression (`${{ ... && 90 || 30 }}`) passes if ANY branch covers the
steps, because which branch applies depends on inputs this test cannot
evaluate. It still catches the case where no branch does. Step budgets are summed on
compatible routes: only necessary, immutable selector equalities prove that
two steps cannot run together; unknown conditions retain their full budget.
"""

import itertools
import math
import re
from pathlib import Path

import pytest
import yaml

from tests.workflow_contracts import (
    expression_body, literal_choices, split_top_level, tokens, unparenthesized,
)

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))


def _budgets(value):
    """Only literal minute budgets, never digits harvested from a condition."""
    if value is None:
        return []
    if type(value) is int and value > 0:
        return [value]
    try:
        if isinstance(value, str):
            raw = value.strip()
            parts = tokens(expression_body(raw) if raw.startswith("${{") else raw)
            choices = literal_choices(parts)
            if all(type(choice) is int for choice in choices):
                return choices
    except ValueError:
        pass
    raise AssertionError(f"cannot prove timeout-minutes budget: {value!r}")


def _selector_constraints(condition):
    """Necessary equalities on immutable selectors; unknown syntax costs time.

    Only conjunctions with nonnumeric ASCII string comparisons get credit.
    In particular, OR, negation and numeric-looking strings cannot establish
    exclusivity (GitHub's loose equality can equate '01' and '1' to a number).
    Strings compare case-insensitively. No condition is evaluated here.
    """
    if not isinstance(condition, str):
        return {}
    try:
        raw = condition.strip()
        parts = tokens(expression_body(raw) if raw.startswith("${{") else raw)
    except ValueError:
        return {}

    def constraints(parts):
        parts = unparenthesized(parts)
        if len(split_top_level(parts, "||")) != 1:
            return {}
        conjuncts = split_top_level(parts, "&&")
        if len(conjuncts) > 1:
            result = {}
            for conjunct in conjuncts:
                for key, value in constraints(conjunct).items():
                    if key in result and result[key] != value:
                        return {}  # contradictory/unknown condition: count it
                    result[key] = value
            return result
        match = re.fullmatch(
            r"((?:inputs|matrix)\.[A-Za-z_][A-Za-z0-9_-]*|github\.event_name)"
            r"=='([A-Za-z][A-Za-z0-9_-]*)'", "".join(parts),
        )
        return {match[1]: match[2].lower()} if match else {}

    try:
        return constraints(parts)
    except ValueError:
        return {}


def _step_total(steps):
    timed = [
        (max(_budgets(step.get("timeout-minutes")), default=0),
         _selector_constraints(step.get("if")))
        for step in steps if isinstance(step, dict)
    ]
    selectors = {}
    for _, constraints in timed:
        for key, value in constraints.items():
            selectors.setdefault(key, set()).add(value)
    # Unrecognised or excessively large selector sets conservatively retain
    # the original sum. The contract must stay cheap on arbitrary workflows.
    if math.prod(len(values) for values in selectors.values()) > 4096:
        return sum(budget for budget, _ in timed)
    # An unlisted selector value only disables constrained steps, so it cannot
    # exceed a listed assignment. Unconditional/opaque steps count on all paths.
    return max((
        sum(budget for budget, constraints in timed
            if all(assignment[key] == value for key, value in constraints.items()))
        for values in itertools.product(*selectors.values())
        for assignment in [dict(zip(selectors, values))]
    ), default=0)


def _cases():
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text()) or {}
        for job_id, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps") or []
            step_total = _step_total(steps)
            if step_total == 0:
                continue  # no step declares a budget; nothing to cover
            yield wf.name, job_id, job.get("timeout-minutes"), step_total


CASES = list(_cases())


@pytest.mark.parametrize(
    "workflow,job_id,job_timeout,step_total",
    CASES,
    ids=[f"{w}:{j}" for w, j, _, _ in CASES],
)
def test_a_job_budget_covers_its_own_steps(workflow, job_id, job_timeout, step_total):
    # An omitted job timeout has GitHub's 360-minute default, not infinity.
    best = 360 if job_timeout is None else max(_budgets(job_timeout), default=0)
    assert best >= step_total, (
        f"{workflow} job '{job_id}': job timeout {job_timeout!r} tops out at "
        f"{best} minutes but its steps declare {step_total}. The job will be "
        f"cancelled with its steps still inside their own limits, and the "
        f"cancellation is indistinguishable from an infrastructure flake."
    )


def test_the_check_has_something_to_check():
    """A parametrized test over an empty list passes while asserting nothing."""
    assert CASES, "no job in .github/workflows declares step-level timeouts"


def _timed(minutes, condition=None):
    return {"timeout-minutes": minutes, "if": condition}


def test_disjoint_selector_routes_do_not_add_impossible_steps():
    steps = [
        _timed(20, "inputs.source == 'archive' && inputs.run != format('{0}', github.run_id)"),
        _timed(60, "steps.filter.outputs.skip != 'true' && github.event_name == 'workflow_dispatch' && inputs.source == 'build'"),
        _timed(60, "steps.filter.outputs.skip != 'true'"),
    ]
    assert _step_total(steps) == 120
    # The reduced total still has to fit, including the common strict phase.
    with pytest.raises(AssertionError, match="steps declare 120"):
        test_a_job_budget_covers_its_own_steps("fixture.yml", "test", 119, _step_total(steps))


def test_all_steps_on_the_same_route_and_unconditional_steps_count():
    assert _step_total([
        _timed(50), _timed(70, "inputs.source == 'build'"),
        _timed(80, "inputs.source == 'BUILD'"), _timed(10, "inputs.source == 'archive'"),
    ]) == 200


def test_nested_conjunctions_and_wrapped_conditions_establish_exclusivity():
    assert _step_total([
        _timed(20, "${{ (inputs.source == 'archive') && (success() && inputs.check) }}"),
        _timed(60, "(inputs.source == 'build' && success())"), _timed(60),
    ]) == 120


@pytest.mark.parametrize("condition", [
    "inputs.source == 'archive' || always()",
    "!(inputs.source == 'build')",
    "inputs.source != 'build'",
    "contains(inputs.source, 'archive')",
    "env.source == 'archive'",
    "steps.previous.outputs.source == 'archive'",
    "inputs.source == 'archive' && (",
    "inputs.source == 'archive' &&",
])
def test_unknown_conditions_never_discount_budget(condition):
    assert _step_total([
        _timed(20, condition), _timed(60, "inputs.source == 'build'"), _timed(60),
    ]) == 140


def test_numeric_string_coercion_cannot_prove_disjoint_routes():
    assert _step_total([
        _timed(70, "inputs.selector == '1'"), _timed(70, "inputs.selector == '01'"),
    ]) == 140


def test_large_selector_space_falls_back_to_full_budget():
    steps = [
        _timed(1, f"inputs.selector{i} == '{value}'")
        for i in range(13) for value in ("a", "b")
    ]
    assert _step_total(steps) == 26


def test_numbers_inside_predicates_do_not_inflate_a_timeout():
    timeout = "${{ inputs.run == '999999' && 20 || (matrix.version == 2404 && 30 || 10) }}"
    assert _budgets(timeout) == [20, 30, 10]
    with pytest.raises(AssertionError, match="steps declare 31"):
        test_a_job_budget_covers_its_own_steps("fixture.yml", "test", timeout, 31)


@pytest.mark.parametrize("value", [
    True, False, 0, -1, [], {}, "not-a-budget-999", "${{ inputs.timeout }}",
    "${{ inputs.timeout || 999 }}", "${{ inputs.fast && '999' || 10 }}",
    "${{ inputs.fast && 10 || inputs.fallback }}", "${{ 10 }} trailing",
    "${{ inputs.fast && 10 || 20 || 999 }}",
    "${{ (inputs.timeout || inputs.fast && 10) || 20 }}",
])
def test_unprovable_timeouts_fail_closed(value):
    with pytest.raises(AssertionError, match="cannot prove timeout-minutes"):
        _budgets(value)


def test_github_default_job_timeout_is_finite():
    test_a_job_budget_covers_its_own_steps("fixture.yml", "test", None, 360)
    with pytest.raises(AssertionError, match="steps declare 361"):
        test_a_job_budget_covers_its_own_steps("fixture.yml", "test", None, 361)
