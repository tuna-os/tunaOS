"""`just fix` must be a no-op on a clean tree, and `just check` must enforce it.

Three separate faults made `just fix` rewrite 145 files and 12,277 lines on a
clean checkout of main, while AGENTS.md makes `just fix && just check`
mandatory before every commit:

1. `.editorconfig` declared `indent_style = space` / `indent_size = 2` for
   shell, while 100% of the shell code is written with tabs (15 of 15
   build_scripts/*.sh) -- and shfmt reads `.editorconfig`.
2. `just fix` ran shfmt over `_upstream-snapshots/`, vendored upstream code
   whose whole value is being byte-identical to what upstream ships.
3. `just check` never ran shfmt at all, so nothing ever noticed 1 or 2.

These tests pin the shape of the fix, not the formatting itself -- the
formatting is enforced by `just check`.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITORCONFIG = ROOT / ".editorconfig"
UTILITIES = ROOT / "just" / "utilities.just"


def _recipe(name: str) -> str:
    text = UTILITIES.read_text()
    body = text[text.index(f"\n{name}:"):]
    nxt = re.search(r"\n[a-z][a-z0-9-]*:", body[1:])
    return body[: nxt.start() + 1] if nxt else body


def test_editorconfig_matches_the_code_it_formats() -> None:
    """Tabs, because that is what every shell file in the repo uses."""
    text = EDITORCONFIG.read_text()
    block = text[text.index("[*.{sh,bash}]"):]
    block = block[: block.index("\n[", 1)] if "\n[" in block[1:] else block
    assert "indent_style = tab" in block
    assert "indent_style = space" not in block


def test_fix_does_not_reformat_vendored_upstream_code() -> None:
    """_upstream-snapshots is kept to match upstream byte for byte.

    Both loops need the exclusion, not just the shell one. The `.just` loop
    had none, so the automation bot reformatted a vendored
    zirconium/...67-gamerslop.just and opened a PR for it on every run --
    #2421, #2422 and #2423 were three identical rewrites of that same file,
    regenerated as fast as they were rejected.
    """
    fix = _recipe("fix")
    for loop in ('-iname "*.sh"', '-name "*.just"'):
        line = next(l for l in fix.splitlines() if loop in l)
        assert "_upstream-snapshots" in line, f"vendored tree not excluded from {loop}"


def test_check_verifies_shell_formatting() -> None:
    """A formatter you do not verify is a formatter that drifts."""
    assert "shfmt" in _recipe("check")


def test_the_formatting_gate_can_actually_fail() -> None:
    """`find -exec shfmt --diff {} \;` returns 0 even when shfmt exits 1.

    find does not propagate the child's status, so the obvious spelling of
    this check is a gate that can never fail — the same dead-gate shape
    AGENTS.md warns about. Measured: shfmt --diff on a badly formatted file
    exits 1; the identical command under `find -exec` exits 0. The check must
    therefore test shfmt's OUTPUT (`shfmt -l`), not an exit status.
    """
    check = _recipe("check")
    assert "shfmt -l" in check
    # Check the CODE, not the prose: the recipe's comment deliberately spells
    # out the broken form so the next reader does not reintroduce it, and a
    # test that forbids naming the trap forbids documenting it.
    code = "\n".join(
        line for line in check.splitlines() if not line.lstrip().startswith("#")
    )
    assert not re.search(r"-exec\s+shfmt\s+--diff", code)
