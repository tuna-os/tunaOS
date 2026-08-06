#!/usr/bin/env python3
"""Unit tests for scripts/gen-matrix-status.py's drift semantics.

The regression these pin down: the Provenance table names the run that asserted
each verdict, so it advances whenever a cell is RE-RUN, even to the identical
verdict. `LUKS guppy:xfce` went ❌ -> ❌ across runs 31091141499 and
31099697401, no cell moved, and the generated block still changed — which
failed the pull_request drift gate (run 31109653582) on a one-row diff and
would have opened a no-op refresh PR daily.

So "the document is stale" has to mean "a verdict moved", not "the bytes
differ". These tests assert that distinction in both directions: provenance
churn is not drift, and a real cell move still is.

Run with: pytest tests/pytest/test_gen_matrix_status.py -v
"""

import importlib.util
import pathlib

import pytest

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2] / "scripts" / "gen-matrix-status.py"
)
DOC_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "MATRIX-STATUS.md"
)


@pytest.fixture()
def mod():
    """Load the generator as a module (its filename has a hyphen).

    Nothing here calls build(), so no GitHub API access happens: the tests
    substitute a block for it.
    """
    spec = importlib.util.spec_from_file_location("gen_matrix_status", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make_doc(mod, provenance_run="31091141499", yellowfin="✅"):
    """A minimal document with the same marker layout as the real one."""
    return (
        "# hand-written head\n"
        "\n"
        f"{mod.BEGIN}\n"
        "\n"
        "| Variant | gnome |\n"
        "|---|---|\n"
        f"| **yellowfin** | {yellowfin} |\n"
        "\n"
        f"{mod.VOLATILE_BEGIN}\n"
        "\n"
        "## Provenance\n"
        "\n"
        "| Date | Run | Cells |\n"
        "|---|---|---|\n"
        f"| 2026-08-06 | [{provenance_run}](url) | 1 |\n"
        "\n"
        f"{mod.VOLATILE_END}\n"
        "\n"
        f"{mod.END}\n"
        "\n"
        "## hand-written tail\n"
    )


def block_of(mod, text):
    """The BEGIN..END slice, i.e. what build() is responsible for producing."""
    start = text.index(mod.BEGIN)
    end = text.index(mod.END) + len(mod.END)
    return text[start:end]


# ── stable_view ──────────────────────────────────────────────────────────────


def test_provenance_churn_is_not_a_stable_change(mod):
    """The exact 31091141499 -> 31099697401 swap that failed the gate."""
    before = make_doc(mod, provenance_run="31091141499")
    after = make_doc(mod, provenance_run="31099697401")
    assert before != after, "the fixture must actually differ"
    assert mod.stable_view(before) == mod.stable_view(after)


def test_a_moved_cell_is_a_stable_change(mod):
    """Mutation check: the fence must not swallow real verdict changes."""
    before = make_doc(mod, yellowfin="✅")
    after = make_doc(mod, yellowfin="❌")
    assert mod.stable_view(before) != mod.stable_view(after)


def test_stable_view_keeps_hand_written_prose(mod):
    """A hand-edit outside the block still has to be visible to the gate."""
    before = make_doc(mod)
    after = before.replace("hand-written tail", "hand-edited tail")
    assert mod.stable_view(before) != mod.stable_view(after)


def test_stable_view_collapses_only_the_volatile_body(mod):
    view = mod.stable_view(make_doc(mod))
    assert "## Provenance" not in view
    assert "31091141499" not in view
    # The fence itself survives, so a deleted fence is not mistaken for a
    # collapsed one.
    assert mod.VOLATILE_BEGIN + mod.VOLATILE_END in view
    assert "| **yellowfin** | ✅ |" in view


# ── main(): the write / --check decision ─────────────────────────────────────


def run_main(mod, monkeypatch, tmp_path, committed, regenerated, argv):
    doc = tmp_path / "MATRIX-STATUS.md"
    doc.write_text(committed)
    monkeypatch.setattr(mod, "DOC", doc)
    monkeypatch.setattr(mod, "build", lambda: block_of(mod, regenerated))
    monkeypatch.setattr(mod.sys, "argv", argv)
    return mod.main(), doc.read_text()


def test_provenance_only_churn_leaves_the_file_untouched(mod, monkeypatch, tmp_path):
    """The fix: no rewrite, so `git diff --quiet` stays clean and the gate passes."""
    committed = make_doc(mod, provenance_run="31091141499")
    rc, after = run_main(
        mod,
        monkeypatch,
        tmp_path,
        committed,
        make_doc(mod, provenance_run="31099697401"),
        ["gen-matrix-status.py"],
    )
    assert rc == 0
    assert after == committed


def test_provenance_only_churn_passes_check(mod, monkeypatch, tmp_path):
    rc, _ = run_main(
        mod,
        monkeypatch,
        tmp_path,
        make_doc(mod, provenance_run="31091141499"),
        make_doc(mod, provenance_run="31099697401"),
        ["gen-matrix-status.py", "--check"],
    )
    assert rc == 0


def test_a_moved_cell_still_rewrites_the_file(mod, monkeypatch, tmp_path):
    """Mutation check: the gate must still catch a genuinely stale scoreboard."""
    committed = make_doc(mod, yellowfin="✅")
    rc, after = run_main(
        mod,
        monkeypatch,
        tmp_path,
        committed,
        make_doc(mod, yellowfin="❌"),
        ["gen-matrix-status.py"],
    )
    assert rc == 0
    assert after != committed
    assert "| **yellowfin** | ❌ |" in after


def test_a_moved_cell_still_fails_check(mod, monkeypatch, tmp_path):
    rc, _ = run_main(
        mod,
        monkeypatch,
        tmp_path,
        make_doc(mod, yellowfin="✅"),
        make_doc(mod, yellowfin="❌"),
        ["gen-matrix-status.py", "--check"],
    )
    assert rc == 1


def test_a_moved_cell_refreshes_provenance_with_it(mod, monkeypatch, tmp_path):
    """Provenance is excluded from the COMPARISON, not from the output."""
    _, after = run_main(
        mod,
        monkeypatch,
        tmp_path,
        make_doc(mod, provenance_run="31091141499", yellowfin="✅"),
        make_doc(mod, provenance_run="31099697401", yellowfin="❌"),
        ["gen-matrix-status.py"],
    )
    assert "31099697401" in after
    assert "31091141499" not in after


# ── the committed artifact ───────────────────────────────────────────────────


def test_committed_doc_fences_provenance(mod):
    """Guards against the fence being defined but never emitted by build()."""
    text = DOC_PATH.read_text()
    for marker in (mod.BEGIN, mod.VOLATILE_BEGIN, mod.VOLATILE_END, mod.END):
        assert marker in text, f"missing {marker!r}"
    # Provenance has to sit INSIDE the fence, and the fence inside the block.
    assert (
        text.index(mod.BEGIN)
        < text.index(mod.VOLATILE_BEGIN)
        < text.index("## Provenance")
        < text.index(mod.VOLATILE_END)
        < text.index(mod.END)
    )


def test_committed_doc_has_no_provenance_outside_the_fence(mod):
    """The run-ID churn must be entirely inside the collapsed region."""
    view = mod.stable_view(DOC_PATH.read_text())
    assert "## Provenance" not in view
    assert "/actions/runs/" not in view
