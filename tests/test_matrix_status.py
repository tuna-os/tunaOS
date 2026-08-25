#!/usr/bin/env python3
"""Unit tests for the structural comparison in scripts/gen-matrix-status.py.

docs/MATRIX-STATUS.md is generated from live Actions data, so its cells, tallies
and provenance rows move whenever any run in the repo completes. The
pull_request drift gate used to compare bytes, which meant a LUKS run landing
mid-review failed the PR for something the PR neither caused nor could fix.
`--check-structure` masks that live content instead. These tests pin both halves
of that contract: live churn is ignored, and the things a PR really can break
(hand-edits inside the generated block, cells build-config stops scheduling) are
still caught.
"""

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status"] = gms
_spec.loader.exec_module(gms)


BLOCK = """\
<!-- BEGIN GENERATED — scripts/gen-matrix-status.py -->

## LUKS E2E

**10 of 54** cells green (12 tested, 42 never tested).

| Variant | gnome | kde | cosmic | niri | xfce |
|---|:--:|:--:|:--:|:--:|:--:|
| **guppy** | ⬜ | ⬜ | — | — | ❌ |
| **marlin** | ✅ | ⬜ | ⬜ | ⬜ | ⬜ |

NVIDIA cells are **out of scope** for this workflow — 25 stale result(s) remain.

Newest result 2026-08-06, oldest still-authoritative result 2026-08-05.

## Live overlay

**41** tags published.

Missing for 6 ISO cell(s): `gurnard-pantheon`, `hummingbird-base`

## Provenance

| Date | Run | Cells |
|---|---|---|
| 2026-08-06 | [31059184838](https://github.com/tuna-os/tunaOS/actions/runs/31059184838) | 1 |

<!-- END GENERATED -->"""


def normalized(block, other=None):
    """Mirror what --check-structure does, including the shared-row pairing."""
    if other is None:
        return gms.structural(block)
    shared = gms.table_rows(block) & gms.table_rows(other)
    return gms.structural(block, shared)


class LiveChurnIsIgnored(unittest.TestCase):
    def assertSameStructure(self, other):
        self.assertEqual(normalized(BLOCK, other), normalized(other, BLOCK))

    def test_cell_results_flipping(self):
        self.assertSameStructure(
            BLOCK.replace("| **marlin** | ✅ | ⬜", "| **marlin** | ❌ | ✅")
        )

    def test_tally_moving(self):
        self.assertSameStructure(
            BLOCK.replace("**10 of 54** cells green (12 tested, 42 never tested).",
                          "**3 of 54** cells green (41 tested, 13 never tested).")
        )

    def test_provenance_rows_churning(self):
        churned = BLOCK.replace(
            "| 2026-08-06 | [31059184838](https://github.com/tuna-os/tunaOS/"
            "actions/runs/31059184838) | 1 |",
            "| 2026-08-06 | [31092676972](https://github.com/tuna-os/tunaOS/"
            "actions/runs/31092676972) | 4 |\n"
            "| 2026-07-31 | [30601507789](https://github.com/tuna-os/tunaOS/"
            "actions/runs/30601507789) | 5 |",
        )
        self.assertSameStructure(churned)

    def test_data_freshness_line_moving(self):
        self.assertSameStructure(
            BLOCK.replace("Newest result 2026-08-06, oldest still-authoritative "
                          "result 2026-08-05.",
                          "Newest result 2026-08-07, oldest still-authoritative "
                          "result 2026-08-06.")
        )

    def test_nvidia_stale_note_disappearing(self):
        # The sentence exists only while stale pre-exclusion results remain, so
        # it vanishes on its own as they age out.
        self.assertSameStructure(
            BLOCK.replace("NVIDIA cells are **out of scope** for this workflow "
                          "— 25 stale result(s) remain.\n\n", "")
        )

    def test_overlay_inventory_changing(self):
        published = BLOCK.replace("**41** tags published.", "**43** tags published.")
        published = published.replace(
            "Missing for 6 ISO cell(s): `gurnard-pantheon`, `hummingbird-base`",
            "Every non-NVIDIA ISO cell has an overlay.",
        )
        self.assertSameStructure(published)

    def test_row_that_only_a_run_created(self):
        # variants_in_scope() adds a row for any variant a run touched, so rows
        # for variants the matrix does not schedule appear and vanish with the
        # run window alone.
        with_row = BLOCK.replace(
            "| **marlin** |",
            "| **gurnard** | — | — | — | — | — |\n| **marlin** |",
        )
        self.assertSameStructure(with_row)


class RealDriftIsCaught(unittest.TestCase):
    def assertDrifted(self, other):
        self.assertNotEqual(normalized(BLOCK, other), normalized(other, BLOCK))

    def test_hand_edited_narrative(self):
        self.assertDrifted(BLOCK.replace("## LUKS E2E", "## LUKS E2E (all green)"))

    def test_section_deleted(self):
        self.assertDrifted(BLOCK.replace("## Live overlay\n\n**41** tags "
                                         "published.\n\n", ""))

    def test_cell_stops_being_scheduled(self):
        # NA is structure, not live state: it means build-config schedules
        # nothing for that cell, so — flipping to a result must still fail.
        self.assertDrifted(
            BLOCK.replace("| **guppy** | ⬜ | ⬜ | — | — | ❌ |",
                          "| **guppy** | ⬜ | ⬜ | ⬜ | — | ❌ |")
        )

    def test_column_removed(self):
        self.assertDrifted(
            BLOCK.replace("| Variant | gnome | kde | cosmic | niri | xfce |",
                          "| Variant | gnome | kde | cosmic | niri |")
        )


class RunWindowCountsCompletedRuns(unittest.TestCase):
    """Queued and in-progress runs must not consume the window.

    They carry no results, so letting them occupy slots demoted cells a
    completed run had already asserted back to "never tested" — a status page
    quietly downgrading itself, which is what this document exists to prevent.
    """

    def test_in_flight_runs_do_not_shrink_coverage(self):
        completed = [
            {"databaseId": 100 + i, "createdAt": "2026-08-06T00:00:00Z",
             "status": "completed"}
            for i in range(gms.RUN_DEPTH)
        ]
        in_flight = [
            {"databaseId": 900 + i, "createdAt": "2026-08-06T12:00:00Z",
             "status": "in_progress"}
            for i in range(10)
        ]
        listed = in_flight + completed
        viewed = []

        def fake_gh_json(*args):
            if args[1] == "list":
                self.assertIn("--limit", args)
                limit = int(args[args.index("--limit") + 1])
                return listed[:limit]
            run_id = args[2]
            viewed.append(run_id)
            return {"jobs": [{"name": f"LUKS v{run_id}:gnome",
                              "conclusion": "success"}]}

        original = gms.gh_json
        gms.gh_json = fake_gh_json
        try:
            results = gms.latest_results("luks-e2e.yml", r"^LUKS ")
        finally:
            gms.gh_json = original

        self.assertEqual(len(viewed), gms.RUN_DEPTH)
        self.assertEqual(len(results), gms.RUN_DEPTH)
        self.assertTrue(all(int(r) < 900 for r in viewed))


class TruncationWarningTracksTheWindow(unittest.TestCase):
    """The "raise RUN_DEPTH" warning must key off the walk, not the fetch.

    RUN_DEPTH has been outgrown twice, and both times the only symptom was cells
    quietly reading ⬜ "never tested", so the warning is the thing that decides
    when to raise it. Now that the fetch is deliberately wider than the window
    (FETCH_DEPTH), the size of the fetched list says nothing about whether the
    walk was cut short — only hitting the RUN_DEPTH cap does.
    """

    def _walk(self, listed):
        def fake_gh_json(*args):
            if args[1] == "list":
                limit = int(args[args.index("--limit") + 1])
                return listed[:limit]
            run_id = args[2]
            return {"jobs": [{"name": f"LUKS v{run_id}:gnome",
                              "conclusion": "success"}]}

        original, err = gms.gh_json, io.StringIO()
        gms.gh_json = fake_gh_json
        try:
            with contextlib.redirect_stderr(err):
                gms.latest_results("luks-e2e.yml", r"^LUKS ")
        finally:
            gms.gh_json = original
        return err.getvalue()

    @staticmethod
    def _runs(count, status, first_id):
        return [
            {"databaseId": first_id + i, "createdAt": "2026-08-06T00:00:00Z",
             "status": status}
            for i in range(count)
        ]

    def test_warns_when_the_cap_cut_the_walk_short(self):
        # Every run contributes a cell no newer run had, so the deepest one we
        # were allowed to look at was still mid-discovery.
        err = self._walk(self._runs(gms.RUN_DEPTH + 25, "completed", 100))
        self.assertIn("Raise RUN_DEPTH", err)

    def test_silent_when_completed_runs_ran_out_before_the_cap(self):
        # A wide fetch that is mostly in-flight: the walk ends because there is
        # nothing left to walk, not because the window truncated it, so there is
        # no reason to believe a deeper window would find more. Keying the guard
        # off len(runs) instead of the walked count warns here spuriously.
        listed = (self._runs(gms.RUN_DEPTH - 1, "completed", 100)
                  + self._runs(50, "in_progress", 900))
        self.assertGreaterEqual(len(listed), gms.RUN_DEPTH)
        self.assertEqual(self._walk(listed), "")


class UndeclaredCellsAreNotCountedAgainstUs(unittest.TestCase):
    """A cell build-config no longer schedules is out of scope, not failing.

    flounder:cosmic and flounder-sid:cosmic were removed on purpose in 491544d1
    ("drop the COSMIC flavours Debian cannot build"). Their last results are
    still in the run window, and tally() used to enter any cell with a result
    into the denominator — so the LUKS line read "39 of 54" when the live set
    was 52, with two cells no run could ever turn green.

    That is the failure nvidia_tally() already documents: a gap reported as if
    someone should close it, which is its own kind of dishonest status page.
    These tests hold the line in both directions — undeclared cells leave the
    count, and declared ones stay in it however they did.
    """

    KEY = staticmethod(lambda v, d: f"LUKS {v}:{d}")

    # flounder ships gnome/kde/xfce and no longer ships cosmic.
    MATRIX = {"flounder": {"gnome", "kde", "xfce"}}

    def test_a_removed_flavor_leaves_the_denominator(self):
        results = {
            "LUKS flounder:gnome": ("success", "2026-08-06"),
            "LUKS flounder:kde": ("success", "2026-08-06"),
            "LUKS flounder:xfce": ("success", "2026-08-06"),
            "LUKS flounder:cosmic": ("failure", "2026-08-01"),
        }
        total, tested, passed = gms.tally(self.MATRIX, results, self.KEY)
        self.assertEqual((total, tested, passed), (3, 3, 3))

    def test_a_declared_failing_cell_still_counts(self):
        """The guard against reading this as 'hide the reds'."""
        results = {
            "LUKS flounder:gnome": ("success", "2026-08-06"),
            "LUKS flounder:kde": ("failure", "2026-08-06"),
        }
        total, tested, passed = gms.tally(self.MATRIX, results, self.KEY)
        # xfce is declared and untested: in the total, not in tested.
        self.assertEqual((total, tested, passed), (3, 2, 1))

    def test_the_removed_flavor_is_still_disclosed(self):
        """Dropped from the count, but named — not silently forgotten."""
        results = {
            "LUKS flounder:gnome": ("success", "2026-08-06"),
            "LUKS flounder:cosmic": ("failure", "2026-08-01"),
        }
        self.assertEqual(
            gms.undeclared_tally(self.MATRIX, results, self.KEY),
            ["flounder:cosmic"],
        )

    def test_nothing_is_disclosed_once_the_result_ages_out(self):
        """The count has to be able to reach zero, or it is just noise."""
        results = {"LUKS flounder:gnome": ("success", "2026-08-06")}
        self.assertEqual(
            gms.undeclared_tally(self.MATRIX, results, self.KEY), []
        )

    def test_an_undeclared_cell_with_no_result_is_not_disclosed(self):
        """Never-tested and never-scheduled is not a stale result."""
        self.assertEqual(gms.undeclared_tally(self.MATRIX, {}, self.KEY), [])

    def test_the_disclosure_does_not_trip_the_drift_gate(self):
        """It appears and vanishes with the run window, like the NVIDIA note.

        The pull_request gate compares structure with live-derived content
        masked. A paragraph that exists only while a stale result does is live
        content: without a VOLATILE_LINE entry it would fail every PR opened
        while such a result sits in the window, for something no PR caused.
        """
        line = (
            "The table above still shows a result for `flounder:cosmic`. "
            "`.github/build-config.yml` no longer declares that flavour, so "
            "..."
        )
        self.assertRegex(line, gms.VOLATILE_LINE)
        # Control: an ordinary narrative line is NOT masked, so this is not
        # passing because the regex matches everything.
        self.assertNotRegex(
            "This is the only axis that checks a human could actually install.",
            gms.VOLATILE_LINE,
        )

    def test_the_real_build_config_declares_51_luks_cells(self):
        """Ties the unit tests above to the actual denominator on disk.

        If this number moves, the LUKS total moves with it, and that should be
        a deliberate build-config edit rather than a surprise.

        52 -> 53 on 2026-08-25: wahoo (Fedora ELN) declares one desktop
        flavor, gnome, with build_image: true. luks-e2e.yml builds its matrix
        from build_image with no experimental filter, so the cell is real and
        counted rather than quietly excluded — it costs one boot in the
        monthly sweep (`0 7 1 * *`), and nothing nightly, because the variant
        is dispatch-only.

        53 -> 51 on 2026-08-25: hummingbird stopped declaring kde and niri.
        Neither had a `packages.hummingbird` section in
        manifests/desktops/*.yaml -- 0 packages against gnome's 52 -- so
        neither could ever have installed a desktop, and both were failing
        their image build. The denominator going DOWN by two is the point:
        those two cells were counted as owed and could never be paid, and
        while they failed beside gnome they also skipped gnome's ISO
        (tuna-os/tunaOS#2059). Re-declaring either flavor puts its cell back.
        """
        matrix = gms.luks_matrix()
        self.assertEqual(sum(len(v) for v in matrix.values()), 51)
        # The control that makes the drop specific rather than merely smaller:
        # hummingbird keeps exactly the desktops it has package sets for.
        self.assertEqual(matrix.get("hummingbird"), {"gnome", "cosmic"})
        self.assertEqual(matrix.get("wahoo"), {"gnome"})
        self.assertNotIn("cosmic", matrix.get("flounder", set()))
        self.assertNotIn("cosmic", matrix.get("flounder-sid", set()))
        # A control: the flavours flounder DOES declare are still there, so
        # this is not passing because the matrix came back empty.
        self.assertEqual(matrix.get("flounder"), {"gnome", "kde", "xfce"})


if __name__ == "__main__":
    unittest.main()
