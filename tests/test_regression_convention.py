"""Every incident regression test names its incident, and vice versa.

tests/regressions/README.md sets the rule: a bug that let an unusable or
wrongly-promoted image ship is fixed when a test proves the old failure mode
cannot silently recur, and that test is named after the issue. This file is
what makes the rule cost something — a regression test that does not say
which incident it guards is just a test, and a file named for an issue whose
body never mentions it is a name nobody can check.

Adopted from Hive practice #5 in epic #2250.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGRESSIONS = ROOT / "tests" / "regressions"
NAME = re.compile(r"^test_issue_(\d+)_[a-z0-9_]+\.py$")

FILES = sorted(p for p in REGRESSIONS.glob("test_*.py"))


def test_the_directory_exists_and_is_documented():
    assert (REGRESSIONS / "README.md").is_file()
    assert FILES, "tests/regressions/ has no tests; #858 was the seed"


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_the_file_is_named_after_its_issue(path):
    assert NAME.match(path.name), (
        f"{path.name}: expected test_issue_<number>_<what_must_not_recur>.py"
    )


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_the_docstring_opens_with_the_issue_it_guards(path):
    number = NAME.match(path.name).group(1)
    src = path.read_text(encoding="utf-8")
    m = re.match(r'\s*"""(.*?)"""', src, re.S)
    assert m, f"{path.name}: no module docstring"
    first_line = m.group(1).strip().splitlines()[0]
    assert f"#{number}" in first_line, (
        f"{path.name}: the docstring's first line must cite tunaOS#{number}; "
        f"got {first_line!r}"
    )


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_the_test_asserts_something(path):
    src = path.read_text(encoding="utf-8")
    assert re.search(r"^def test_", src, re.M), f"{path.name}: no test functions"
    assert "assert" in src, f"{path.name}: no assertions"


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_the_docstring_says_how_the_test_fails(path):
    """Every regression test states what makes it go red on the unfixed tree.

    A test that cannot fail is indistinguishable from a test that passes, and
    the difference is invisible in a green run. Measured on this repo: three
    assertions in build_scripts/checks/e2e-runtime-checks.sh executed on every
    cell for months while being structurally incapable of passing, and a shell
    formatting gate written the same week used `find -exec`, which returns 0
    even when the command it runs exits 1.

    Two shapes are acceptable -- behavioural (the test drives the real code
    with the broken input, so it falsifies itself) and structural (someone
    reverted the fix and watched it go red). The line should make clear which,
    and a structural claim should name what was reverted.
    """
    src = path.read_text(encoding="utf-8")
    m = re.match(r'\s*"""(.*?)"""', src, re.S)
    assert m, f"{path.name}: no module docstring"
    doc = m.group(1)
    assert "Falsification:" in doc, (
        f"{path.name}: no `Falsification:` line. State what makes this test "
        "red on the unfixed tree -- see tests/regressions/README.md."
    )
    claim = doc.split("Falsification:", 1)[1].strip()
    assert len(claim) > 30, (
        f"{path.name}: the Falsification line is too short to say anything: "
        f"{claim!r}"
    )

