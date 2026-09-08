"""A gate that cannot return non-zero is not a gate.

Epic #2250's premise for the CI contract is that "a test existing in the
repository is not the same as a test being run". This file guards the step
after that one: **a test being run is not the same as a test that can fail.**

Measured on this repo, all executing on every run and none able to report a
regression:

  * three assertions in build_scripts/checks/e2e-runtime-checks.sh were red on
    every cell for months -- graphical.target asserted from inside its own
    startup transaction, a unit-graph check failing on upstream units plus a
    man-page check on an image that strips man pages, and an sshd host-key
    assertion that fired on images which deliberately disable sshd;
  * a shell formatting gate used `find ... -exec shfmt --diff {} \;`, which
    returns 0 even when shfmt exits 1, because find does not propagate the
    child's status. Measured both ways to be certain.

The shapes below are mechanical and cheap to detect. They are not the only
ways to write an unfailable gate, and passing this file does not mean a gate
works -- only that it is not broken in one of the ways that has already
happened here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Scripts whose whole job is to decide pass/fail. Extending this list is the
# point: a new gate should be added here when it is written.
GATE_SCRIPTS = [
    "scripts/iso-e2e.sh",
    "scripts/e2e-smoke-checks.sh",
    "build_scripts/checks/e2e-runtime-checks.sh",
    "build_scripts/checks/verify-desktop-experience.sh",
]

# `find ... -exec <cmd> \;` ALWAYS exits 0, whatever <cmd> returns. Used as the
# condition of an if/||/&& it silently never fires.
FIND_EXEC_AS_CONDITION = re.compile(
    r"(?:if\s+!?\s*|\|\|\s*|&&\s*)find\b[^\n]*-exec\b[^\n]*\;", re.M
)


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", GATE_SCRIPTS)
def test_no_find_exec_used_as_a_pass_fail_condition(rel: str) -> None:
    """`find -exec cmd \;` exits 0 regardless of cmd, so it cannot gate.

    Use `find ... -print0 | xargs -0 cmd`, or capture the output and test it
    -- `shfmt -l` listing files is a gate; `shfmt --diff` under find is not.
    """
    hits = FIND_EXEC_AS_CONDITION.findall(_text(rel))
    assert not hits, (
        f"{rel}: `find -exec` used as a pass/fail condition; it exits 0 "
        f"whatever the command returns: {hits[:2]}"
    )


def test_the_detector_recognises_the_shape_it_is_named_for() -> None:
    """The detector must itself be falsifiable.

    A pattern that matches nothing is the same failure this file exists to
    catch, one level up.
    """
    broken = 'if ! find . -name "*.sh" -exec shfmt --diff "{}" ";"; then\n  exit 1\nfi'
    assert FIND_EXEC_AS_CONDITION.search(broken), "detector misses the real shape"
    fixed = 'out=$(find . -name "*.sh" -print0 | xargs -0 shfmt -l)\nif [[ -n "$out" ]]; then\n  exit 1\nfi'
    assert not FIND_EXEC_AS_CONDITION.search(fixed), "detector flags the correct form"
