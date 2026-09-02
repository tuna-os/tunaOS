# Regression tests: one per incident

A bug that let an unusable or wrongly-promoted image ship is not fixed until
a test proves the old failure mode cannot silently recur. This directory is
where those tests live, and the convention is deliberately mechanical so it
can be checked (`tests/test_regression_convention.py`):

- **File name:** `test_issue_<number>_<what_must_not_recur>.py`, where
  `<number>` is the tunaOS issue that recorded the incident.
- **Docstring:** opens with the issue reference (`tunaOS#<number>`), then
  states what shipped, what was measured, and what the test now holds. State
  the constraint and the run or log that proves it, not the story of how it
  was found (the evidence style in `AGENTS.md`).
- **Assert the failure mode, not the fix.** The test should fail on the tree
  that shipped the incident and pass on the fix — mutate a real input into
  the broken shape where you can, rather than asserting a string is present.

Tests elsewhere in `tests/` already follow the spirit of this (most carry an
issue or run number in their docstring); this directory makes the mapping
from incident to test discoverable by name, so "is #NNN covered?" is a
`ls`, not an archaeology exercise.

Adopted from Hive practice #5 in epic #2250.
