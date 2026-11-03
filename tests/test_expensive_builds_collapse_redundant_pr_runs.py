"""ISO-building workflows must collapse superseded PR runs, but not sweeps.

A `pull_request` paths filter is evaluated against the PR's WHOLE diff, not
the pushed commit. So once a long-lived branch touches one of the watched
paths, every later push to that PR re-triggers the workflow however
unrelated the change. For a ~25-minute ISO build on a RunsOn EC2 instance
that is a real bill: this branch touches `live-iso/**`, and all eight of
one night's pushes started a fresh build while the previous one ran to
completion.

`cancel-in-progress` fixes that. The subtlety is the GROUP KEY. The repo's
usual form is `<name>-${{ github.ref }}`, and on these two workflows that
would be actively harmful: a multi-cell sweep dispatches several runs
against ONE branch, so they would all share a group and cancel each other
down to the last one — a sweep that silently measures a single cell. Two
of those were already lost to a job-budget bug this session; losing them
to a concurrency key would look identical from the outside.

Ordinary dispatches need a group per run; PR pushes need a shared group.
Explicit XFCE candidates instead share one non-cancelling group. CI run
40251533084, job 121344308454, exposed four assertions that could not evaluate
that opt-in exception. Evaluate the declared event/input behavior, not one
expression spelling. Unknown syntax must still fail closed.
"""

from pathlib import Path

import pytest
import yaml

from tests.workflow_contracts import (
    expression_body, interpolations, split_top_level, tokens, unparenthesized,
)

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
# The two that build an ISO on a schedule a human did not ask for: they run
# on `pull_request`, so they are the ones a push storm can multiply.
EXPENSIVE = ["live-iso-bootc.yml", "iso-e2e.yml"]

# The generated per-variant build workflows are the other fan-out: one
# `workflow_dispatch` per flavor (gnome, kde, niri, ...) against ONE branch.
# On 2026-09-06 four such dispatches for albacore shared the group
# `build-albacore-refs/heads/main`: three were cancelled at birth and the
# kde run already in flight lost its walkthrough and R2 upload to the
# newest one. So the same per-run rule applies to them.
GENERATED_BUILDS = sorted(
    f"build-{variant['id']}.yml"
    for variant in (
        yaml.safe_load((WORKFLOWS.parent / "build-config.yml").read_text()) or {}
    ).get("variants", [])
)
assert GENERATED_BUILDS, "no generated build-<variant>.yml workflows found"


def _concurrency(name):
    doc = yaml.safe_load((WORKFLOWS / name).read_text()) or {}
    return doc.get("concurrency")


def _evaluate(parts, context):
    """Bounded Actions subset: bool/string leaves, !, ==/!=, &&/|| and ().

    Logical operators return operands, including the empty missing-input value.
    Check every arm, including an unused one; unknown syntax is never exempt.
    No numeric coercions, functions, Python eval or arbitrary property lookup.
    """
    parts = unparenthesized(parts)
    if not parts:
        raise ValueError("empty expression operand")
    for operator in ("||", "&&"):
        groups = split_top_level(parts, operator)
        if len(groups) > 1:
            values = [_evaluate(group, context) for group in groups]
            value = values[0]
            for other in values[1:]:
                value = (value or other) if operator == "||" else (value and other)
            return value
    for operator in ("==", "!="):
        groups = split_top_level(parts, operator)
        if len(groups) == 2:
            left, right = [_evaluate(group, context) for group in groups]
            if type(left) is not type(right):
                raise ValueError("unsupported comparison coercion")
            if isinstance(left, str):
                left, right = left.lower(), right.lower()
            return (left == right) if operator == "==" else (left != right)
        if len(groups) > 2:
            raise ValueError("unsupported chained comparison")
    if parts[0] == "!":
        return not _evaluate(parts[1:], context)
    if len(parts) == 1:
        token = parts[0]
        if token in ("true", "false"):
            return token == "true"
        if token.startswith("'"):
            return token[1:-1].replace("''", "'")
    name = "".join(parts)
    if len(parts) == 3 and parts[1] == "." and name in context:
        return context[name]
    raise ValueError(f"unsupported concurrency expression: {parts!r}")


def _resolve(c, event, run_id, ref="refs/pull/17/merge", *, candidate="", source=""):
    context = {"github.event_name": event, "github.run_id": run_id,
               "github.ref": ref, "inputs.candidate_xfce": candidate,
               "inputs.source": source}
    group = c["group"]
    for body in interpolations(group):
        value = _evaluate(tokens(body), context)
        if type(value) is not str:
            raise ValueError("concurrency group component must be a string")
        group = group.replace("${{" + body + "}}", value)
    cancellation = c["cancel-in-progress"]
    if type(cancellation) is not bool:
        cancellation = _evaluate(tokens(expression_body(cancellation)), context)
    if type(cancellation) is not bool:
        raise ValueError("cancellation must evaluate to a boolean")
    return group.lower(), cancellation


def _assert_pr(c, candidate=""):
    first = _resolve(c, "pull_request", "101", candidate=candidate)
    second = _resolve(c, "pull_request", "102", candidate=candidate)
    assert first[0] == second[0], "PR pushes must share a group"
    assert first[1] is True and second[1] is True, "PR pushes must cancel superseded runs"
    other = _resolve(c, "pull_request", "103", "refs/pull/18/merge", candidate=candidate)
    assert other[0] != first[0], "unrelated PRs must not cancel each other"


def _assert_sweep(c, candidate=""):
    first = _resolve(c, "workflow_dispatch", "101", "refs/heads/x", candidate=candidate)
    second = _resolve(c, "workflow_dispatch", "102", "refs/heads/x", candidate=candidate)
    assert first[0] != second[0], "ordinary dispatched cells must have separate groups"
    assert first[1] is True and second[1] is True


def _assert_candidate(c):
    first = _resolve(c, "workflow_dispatch", "101", "refs/heads/x",
                     candidate=True, source="native-artifact")
    second = _resolve(c, "workflow_dispatch", "102", "refs/heads/y",
                      candidate=True, source="native-artifact")
    assert first[0] == second[0], "explicit candidates must share one group across refs/runs"
    assert first[1] is False and second[1] is False, "candidates must not cancel active runs"
    for event in ("pull_request", "workflow_dispatch", "schedule"):
        ordinary = _resolve(c, event, "101", "refs/heads/x", source="native-artifact")
        assert first[0] != ordinary[0], "ordinary runs must not cancel active candidates"
    return first[0]


@pytest.mark.parametrize("workflow", EXPENSIVE + GENERATED_BUILDS)
@pytest.mark.parametrize("candidate", ["", False], ids=["missing-input", "default-false"])
def test_it_cancels_superseded_runs(workflow, candidate):
    c = _concurrency(workflow)
    assert c, f"{workflow} has no concurrency block"
    _assert_pr(c, candidate)


@pytest.mark.parametrize("workflow", EXPENSIVE + GENERATED_BUILDS)
@pytest.mark.parametrize("candidate", ["", False], ids=["missing-input", "default-false"])
def test_a_dispatched_sweep_does_not_cancel_itself(workflow, candidate):
    _assert_sweep(_concurrency(workflow), candidate)


@pytest.mark.parametrize("workflow", EXPENSIVE + GENERATED_BUILDS)
def test_pr_pushes_share_one_group(workflow):
    _assert_pr(_concurrency(workflow))


@pytest.mark.parametrize("workflow", EXPENSIVE)
def test_explicit_candidate_serializes_without_cancelling(workflow):
    _assert_candidate(_concurrency(workflow))


def test_candidate_caller_and_consumer_do_not_deadlock_each_other():
    groups = [_assert_candidate(_concurrency(name)) for name in EXPENSIVE]
    assert len(set(groups)) == len(groups)


@pytest.mark.parametrize("workflow", EXPENSIVE)
@pytest.mark.parametrize("fault", ["no-pr-cancel", "candidate-cancel", "reversed-cancel",
                                    "pr-per-run", "sweep-shared", "candidate-per-run"])
def test_behavioral_contract_rejects_broken_concurrency(workflow, fault):
    c = dict(_concurrency(workflow))
    check = _assert_pr
    if fault == "no-pr-cancel":
        c["cancel-in-progress"] = False
    elif fault == "candidate-cancel":
        c["cancel-in-progress"] = True
        check = _assert_candidate
    elif fault == "reversed-cancel":
        c["cancel-in-progress"] = "${{ inputs.candidate_xfce }}"
        check = lambda value: _assert_pr(value, False)
    elif fault == "pr-per-run":
        c["group"] = "broken-${{ github.ref }}-${{ github.run_id }}"
    elif fault == "sweep-shared":
        c["group"] = "broken-${{ github.ref }}"
        check = _assert_sweep
    elif fault == "candidate-per-run":
        c["group"] = "broken-${{ github.run_id }}"
        check = _assert_candidate
    with pytest.raises(AssertionError):
        check(c)


@pytest.mark.parametrize("value", ["${{ inputs.unknown }}", "${{ always() }}",
                                   "${{ true || inputs.unknown }}", "${{ 1 }}",
                                   "${{ false == '' }}", "${{ inputs['candidate_xfce'] }}"])
def test_unknown_or_coerced_expressions_are_not_exempt(value):
    with pytest.raises(ValueError):
        _resolve({"group": "test", "cancel-in-progress": value}, "pull_request", "101")


def test_evaluator_obeys_precedence_operand_values_and_string_equality():
    def evaluate(value):
        return _evaluate(tokens(value), {})
    assert evaluate("false && 'candidate' || 'ordinary'") == "ordinary"
    assert evaluate("true && '' || 'ordinary'") == "ordinary"
    assert evaluate("!(false || true)") is False
    assert evaluate("'PULL_REQUEST' == 'pull_request'") is True
    assert evaluate("true || false && false") is True
