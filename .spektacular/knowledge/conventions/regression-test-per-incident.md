---
tags: [regression, testing, pytest]
---

# Land an incident fix with a regression test and a `Falsification:` line

A fix for a bug that shipped an unusable or wrongly-promoted image lands with `tests/regressions/test_issue_<N>_<what_must_not_recur>.py`. The docstring opens with `tunaOS#<N>`, states the constraint and the evidence, and carries a line starting `Falsification:` that says (behavioural or structural) how the test fails on the unfixed tree. Assert the failure mode, not the fix.

Enforced by `tests/test_regression_convention.py`.

Source: `tests/regressions/README.md`; `AGENTS.md` (Hive conventions, #2250).
