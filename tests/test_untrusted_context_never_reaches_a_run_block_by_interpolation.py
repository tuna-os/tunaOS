"""No `run:` block may interpolate `inputs.*`, `github.event.*` or
`github.head_ref` with `${{ }}`.

A `${{ }}` expression is substituted into the script text *before* bash
parses it, so the shell never sees a variable — it sees whatever the value
was, spliced in verbatim. Double quotes around the expression do not help: a
value containing `"` closes the quoted string early and the rest of it is
parsed as shell. That is the standard GitHub Actions script-injection shape
(#2310, #2295), and the sites it found here were exactly that:

    scripts/asahi-remote-switch.sh "${{ inputs.image }}"
    if [[ -n "${{ inputs.filter }}" ]]; then
    --base "${{ github.event.pull_request.base.sha || github.event.before }}"

The fix is mechanical and the same everywhere: bind the value to a step-level
`env:` entry and reference the shell variable, quoted, inside `run:`. Bash
then handles the value as data, whatever it contains:

    env:
      IMAGE: ${{ inputs.image }}
    run: |
      scripts/asahi-remote-switch.sh "$IMAGE"

Scope is deliberate. `matrix.*`, `steps.*.outputs.*`, `secrets.*` and
`env.*` are workflow-controlled; `github.repository`, `github.run_id`,
`github.sha`, `github.actor` and friends are shaped by GitHub and cannot carry
shell metacharacters. `inputs.*` is whatever the person (or workflow) that
dispatched the run typed; `github.event.*` is the webhook payload, which on
`pull_request` carries branch names, titles and bodies written by anyone who
can open a PR; `github.head_ref` is a PR branch name. Those three are the
untrusted roots and the only ones this test rejects.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)

# Roots whose value is chosen by whoever triggered the run, not by this repo.
UNTRUSTED = re.compile(r"(?<![\w.])(inputs\.|github\.event\.|github\.head_ref\b)")


def untrusted_interpolations(script: str) -> list[str]:
    """Every `${{ }}` body in `script` that reads an untrusted root."""
    return [
        match.group(1).strip()
        for match in EXPRESSION.finditer(script)
        if UNTRUSTED.search(match.group(1))
    ]


def run_blocks(path: Path):
    doc = yaml.safe_load(path.read_text())
    for job_name, job in (doc.get("jobs") or {}).items():
        for index, step in enumerate(job.get("steps") or []):
            script = step.get("run")
            if isinstance(script, str):
                label = step.get("name") or step.get("id") or f"step {index}"
                yield job_name, label, script


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_run_block_interpolates_untrusted_context(path: Path):
    offenders = [
        f"{job}/{step}: ${{{{ {body} }}}}"
        for job, step, script in run_blocks(path)
        for body in untrusted_interpolations(script)
    ]
    assert not offenders, (
        f"{path.name} splices untrusted context into a shell script; bind it "
        "to a step-level env: entry and reference the shell variable instead:\n  "
        + "\n  ".join(offenders)
    )


def test_there_are_workflows_to_check():
    assert len(WORKFLOWS) > 10


def test_the_detector_recognises_the_shapes_it_guards():
    assert untrusted_interpolations('x "${{ inputs.image }}"') == ["inputs.image"]
    assert untrusted_interpolations("${{ inputs.timeout || '300' }}") == ["inputs.timeout || '300'"]
    assert untrusted_interpolations(
        '--base "${{ github.event.pull_request.base.sha || github.event.before }}"'
    ) == ["github.event.pull_request.base.sha || github.event.before"]
    assert untrusted_interpolations("${{ github.head_ref }}") == ["github.head_ref"]
    # Multi-line expressions are still one expression.
    assert untrusted_interpolations("${{\n  inputs.x\n}}") == ["inputs.x"]


def test_the_detector_leaves_trusted_context_alone():
    trusted = (
        '"${{ matrix.variant }}" "${{ secrets.TOKEN }}" "${{ steps.vars.outputs.tag }}" '
        '"${{ github.repository }}" "${{ github.run_id }}" "${{ github.actor }}" '
        '"${{ env.IMAGE }}" "${{ needs.plan.outputs.cells }}" "${{ github.event_name }}"'
    )
    assert untrusted_interpolations(trusted) == []
    # The shell variable the fix leaves behind is not an expression at all.
    assert untrusted_interpolations('scripts/switch.sh "$IMAGE"') == []


def test_a_bound_env_entry_is_the_accepted_form(tmp_path: Path):
    """The fix shape passes; the original shape from #2310 fails."""
    good = tmp_path / "good.yml"
    good.write_text(
        "on: workflow_dispatch\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: switch\n"
        "        env:\n          IMAGE: ${{ inputs.image }}\n"
        '        run: scripts/switch.sh "$IMAGE"\n'
    )
    bad = tmp_path / "bad.yml"
    bad.write_text(
        "on: workflow_dispatch\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: switch\n"
        '        run: scripts/switch.sh "${{ inputs.image }}"\n'
    )
    assert [b for _, _, s in run_blocks(good) for b in untrusted_interpolations(s)] == []
    assert [b for _, _, s in run_blocks(bad) for b in untrusted_interpolations(s)] == [
        "inputs.image"
    ]
