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
