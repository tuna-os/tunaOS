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

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
