"""A workflow expression must not test an input that does not exist.

`${{ inputs.foo == 'x' && 'a' || 'b' }}` on an UNDECLARED input is not an
error. GitHub evaluates the missing input to empty, the comparison is
false, and the expression quietly takes its else-branch forever. The
workflow stays valid, the step runs, and the thing you thought you had
switched on is simply off.

That is not hypothetical: the hummingbird qcow2 filesystem override was
first written as `inputs.variant`, and `reusable-build-image.yml` declares
`image-variant`, not `variant`. It would have run every gate with the
override unset and produced a "the fix did not work" result from a fix
that never applied.

Checks reusable workflows, where the input list is declared and therefore
checkable. `github.event.inputs` on workflow_dispatch is a different
surface and is out of scope here.
"""

from pathlib import Path

import pytest
import yaml

from tests.workflow_contracts import interpolations, tokens

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))



def _workflow_expressions(doc):
    """Read expressions in YAML values, plus implicit job/step if expressions."""
    def walk(value):
        if isinstance(value, str):
            yield from interpolations(value)
        elif isinstance(value, dict):
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    yield from walk(doc)
    for job in (doc.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for owner in [job, *(job.get("steps") or [])]:
            if not isinstance(owner, dict):
                continue
            condition = owner.get("if")
            if isinstance(condition, str) and "${{" not in condition:
                yield condition


def _input_references(expression):
    """Root inputs references, ignoring string literals and other contexts."""
    parts = tokens(expression)
    found = set()
    for index, part in enumerate(parts):
        if part.lower() != "inputs" or (index and parts[index - 1] == "."):
            continue
        following = parts[index + 1:]
        if following and following[0] == ".":
            if len(following) < 2 or not following[1][0].isalpha() and following[1][0] != "_":
                raise ValueError("unsupported inputs property reference")
            found.add(following[1])
        elif following and following[0] == "[":
            if len(following) < 3 or not following[1].startswith("'") or following[2] != "]":
                raise ValueError("dynamic inputs lookup cannot be checked statically")
            found.add(following[1][1:-1].replace("''", "'"))
    return found


def _referenced_inputs(doc):
    found = set()
    for expression in _workflow_expressions(doc):
        try:
            found.update(_input_references(expression))
        except ValueError as error:
            raise AssertionError(f"cannot check workflow expression {expression!r}: {error}") from error
    return found


def _reusable():
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text()) or {}
        on = doc.get("on", doc.get(True)) or {}
        call = on.get("workflow_call") if isinstance(on, dict) else None
        if isinstance(call, dict):
            yield wf, set((call.get("inputs") or {}).keys()), doc


CASES = list(_reusable())


@pytest.mark.parametrize(
    "wf,declared,doc", CASES, ids=[w.name for w, _, _ in CASES]
)
def test_workflow_conditions_name_real_inputs(wf, declared, doc):
    referenced = _referenced_inputs(doc)
    unknown = sorted(referenced - declared)
    assert not unknown, (
        f"{wf.name} references undeclared input(s) {unknown}. Declared: "
        f"{sorted(declared)}. A missing input evaluates empty rather than "
        f"failing, so any condition on it silently takes its else-branch."
    )


def test_the_check_examined_something():
    assert CASES, "no reusable workflow found — the detector is broken"
    assert any(d for _, d, _ in CASES), "no workflow_call inputs found"


def test_shell_filenames_yaml_comments_and_literal_text_are_not_input_references():
    doc = yaml.safe_load("""
# ${{ inputs.comment_only }}
jobs:
  test:
    if: inputs.variant != ''
    env:
      if: inputs.not_a_condition
      VALUE: ${{ inputs['variant'] }}
    steps:
      - if: ${{ inputs.variant == 'gnome' }}
        run: |
          python scripts/collect-inputs.py > inputs.json
          jq '.resolved_inputs.media' inputs.json
          echo inputs.shell_word
          echo "${{ format('inputs.literal }} and ''inputs.escaped''', inputs.variant) }}"
""")
    assert _referenced_inputs(doc) == {"variant"}


@pytest.mark.parametrize("location", ["job-if", "step-if", "env", "run", "shell-comment"])
def test_missing_inputs_are_still_rejected_at_every_expression_location(location):
    step = {}
    job = {"steps": [step]}
    doc = {"jobs": {"test": job}}
    if location == "job-if":
        job["if"] = "inputs.missing == 'yes'"
    elif location == "step-if":
        step["if"] = "inputs['missing'] == 'yes'"
    elif location == "env":
        step["env"] = {"VALUE": "${{ inputs.missing }}"}
    elif location == "run":
        step["run"] = "echo '${{ inputs.missing }}'"
    else:
        step["run"] = "# Even shell comments interpolate: ${{ inputs.missing }}"
    with pytest.raises(AssertionError, match="undeclared input"):
        test_workflow_conditions_name_real_inputs(Path("fixture.yml"), {"declared"}, doc)


def test_root_input_references_include_bracket_access_and_ignore_other_contexts():
    expression = "github.event.inputs.dispatch_only == inputs['image-variant'] && inputs . source != 'inputs.fake'"
    assert _input_references(expression) == {"image-variant", "source"}


def test_all_interpolations_are_checked_after_quoted_closing_braces():
    doc = {"env": {"VALUE": "${{ format('}}', inputs.first) }} / ${{ inputs.second }}"}}
    assert _referenced_inputs(doc) == {"first", "second"}


@pytest.mark.parametrize("expression", [
    "${{ inputs[matrix.selector] }}", "${{ inputs.* }}", "${{ inputs[0] }}",
    "${{ inputs['missing'] }} ${{ inputs['unterminated }}",
    "${{ inputs.missing", "${{ inputs['missing' }}",
])
def test_uncheckable_input_references_fail_closed(expression):
    with pytest.raises((AssertionError, ValueError)):
        _referenced_inputs({"env": {"VALUE": expression}})
