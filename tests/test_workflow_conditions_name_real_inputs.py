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

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
INPUT_REF = re.compile(r"inputs\.([A-Za-z_][A-Za-z0-9_-]*)")


def _reusable():
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text()) or {}
        on = doc.get("on", doc.get(True)) or {}
        call = on.get("workflow_call") if isinstance(on, dict) else None
        if isinstance(call, dict):
            yield wf, set((call.get("inputs") or {}).keys()), wf.read_text()


CASES = list(_reusable())


@pytest.mark.parametrize(
    "wf,declared,text", CASES, ids=[w.name for w, _, _ in CASES]
)
def test_workflow_conditions_name_real_inputs(wf, declared, text):
    referenced = set(INPUT_REF.findall(text))
    unknown = sorted(referenced - declared)
    assert not unknown, (
        f"{wf.name} references undeclared input(s) {unknown}. Declared: "
        f"{sorted(declared)}. A missing input evaluates empty rather than "
        f"failing, so any condition on it silently takes its else-branch."
    )


def test_the_check_examined_something():
    assert CASES, "no reusable workflow found — the detector is broken"
    assert any(d for _, d, _ in CASES), "no workflow_call inputs found"
