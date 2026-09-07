"""No workflow may use a C-style ternary in a GitHub Actions expression.

GitHub Actions expressions have no `? :`. One reached main in b2d29bdb and
cost a whole night of images: the expression failed to PARSE, which fails the
entire workflow file, which fails every caller. All 13 variant nightlies
startup-failed on 2026-08-21 with zero jobs and zero duration, and every
re-dispatch the startup-failure sweeper attempted came back HTTP 422:

    reusable-build-image.yml (Line: 1242, Col: 14): Unexpected symbol: '?'.
    ... (startsWith(inputs.flavor,'cosmic') || ...) ? 'gpu' : 'ubuntu-latest'

The same commit put the same ternary in installer-smoke.yml. That copy was
found and fixed (#1919); this one was not, and sat broken for a day. Fixing
one site of a copy-pasted defect is the recurring shape here, so this checks
every workflow rather than the two known ones.

The correct idiom is `cond && a || b`, which reusable-build-image.yml already
used on line 105 while line 1242 did not.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

# `${{ ... ? ... : ... }}`. Deliberately scoped to expression bodies: a bare
# '?' is legal in ordinary YAML strings, shell, and regexes.
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)


def ternaries(text: str):
    for match in EXPRESSION.finditer(text):
        body = match.group(1)
        # A '?' inside a quoted literal is data, not an operator.
        stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "", body)
        if "?" in stripped:
            yield body.strip()


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_uses_a_ternary_expression(path) -> None:
    found = list(ternaries(path.read_text()))
    assert not found, (
        f"{path.name} uses `? :` in a GitHub Actions expression, which does "
        f"not parse and fails the whole file: {found}\n"
        "Use `cond && a || b` instead."
    )


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_workflow_is_valid_yaml(path) -> None:
    """A parse failure here is the cheap half of what CI would find late."""
    yaml.safe_load(path.read_text())


def test_the_detector_catches_the_expression_that_actually_broke_main() -> None:
    """Verbatim from reusable-build-image.yml line 1242 as it stood."""
    broken = (
        "runs-on: >-\n"
        "  ${{ (startsWith(inputs.flavor, 'cosmic') || "
        "startsWith(inputs.flavor, 'niri')) ? 'gpu' : 'ubuntu-latest' }}\n"
    )
    assert list(ternaries(broken))


def test_the_detector_does_not_flag_the_correct_idiom() -> None:
    ok = "runs-on: ${{ contains(matrix.platform, 'amd64') && 'a' || 'b' }}\n"
    assert not list(ternaries(ok))


def test_a_question_mark_inside_a_string_literal_is_not_a_ternary() -> None:
    """Otherwise the check would fire on legitimate text and get disabled."""
    ok = "run: echo ${{ format('does it? yes', github.sha) }}\n"
    assert not list(ternaries(ok))
