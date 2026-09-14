#!/usr/bin/env python3
"""A paragraph that appears with live CI state must not fail a pull request.

`--check-structure` exists to catch exactly two things: a hand-edit inside the
generated block, and a generator broken by a build-config change. Its own
docstring says so, and says why — "it was instead failing on repo-wide CI churn
... the gate went red for reasons the PR neither caused nor can fix, and the
only 'fix' available was committing another snapshot that went stale in
minutes".

It went red on tunaOS#2512 for precisely that reason. The desktop-contract
section ends with a caveat paragraph that `gen-matrix-status.py` emits only
while the newest sweep has a cell that neither passed nor failed. A sweep
finished between the commit and the check, one cell came back `missing`, and
the paragraph appeared:

    +N cell(s) in the most recent sweep are missing (no published image),
    +errored (registry/runner trouble), or lost (job produced no result)...

Masking is per line, so it cannot touch a line that is absent from one side.
A paragraph whose *existence* is live state has to be named in VOLATILE_LINE
explicitly, which is what these tests pin.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen-matrix-status.py"

_spec = importlib.util.spec_from_file_location("gen_matrix_status_drift", SCRIPT)
gms = importlib.util.module_from_spec(_spec)
sys.modules["gen_matrix_status_drift"] = gms
_spec.loader.exec_module(gms)

CAVEAT = (
    "1 cell(s) in the most recent sweep are missing (no published image), "
    "errored (registry/runner trouble), or lost (job produced no result) "
    "rather than a clean pass or fail — not counted above; see that sweep's "
    "own `desktop-contract-baseline` artifact for which."
)


class ASweepFinishingMidReviewIsNotDrift(unittest.TestCase):
    def test_the_caveat_paragraph_is_treated_as_live_state(self):
        self.assertTrue(gms.VOLATILE_LINE.match(CAVEAT))

    def test_any_count_of_such_cells_is_masked_not_just_one(self):
        for n in (1, 2, 14):
            with self.subTest(n=n):
                self.assertTrue(
                    gms.VOLATILE_LINE.match(CAVEAT.replace("1 cell(s)", f"{n} cell(s)", 1))
                )

    def test_a_block_that_gains_the_paragraph_is_structurally_identical(self):
        # The exact shape of the tunaOS#2512 failure: same document, one
        # paragraph added by a sweep nobody in the PR triggered.
        before = "## Desktop contract\n\n| **wahoo** | ? |\n\n## Bootc Lifecycle\n"
        after = f"## Desktop contract\n\n| **wahoo** | ? |\n\n{CAVEAT}\n\n## Bootc Lifecycle\n"
        rows = gms.table_rows(before) & gms.table_rows(after)
        self.assertEqual(gms.structural(before, rows), gms.structural(after, rows))

    def test_a_hand_edit_to_the_prose_still_fails(self):
        # Vacuity guard (tunaOS#1730): the test above passes trivially if
        # structural() starts returning a constant. Prove it still discriminates.
        before = "## Desktop contract\n\nPulls the published image.\n"
        after = "## Desktop contract\n\nPulls the published image, usually.\n"
        rows = gms.table_rows(before) & gms.table_rows(after)
        self.assertNotEqual(gms.structural(before, rows), gms.structural(after, rows))

    def test_a_line_that_merely_mentions_a_sweep_is_not_masked(self):
        # The mask is anchored and shaped, not a substring search for "sweep".
        self.assertIsNone(
            gms.VOLATILE_LINE.match("The sweep runs the contract against every cell.")
        )


if __name__ == "__main__":
    unittest.main()
