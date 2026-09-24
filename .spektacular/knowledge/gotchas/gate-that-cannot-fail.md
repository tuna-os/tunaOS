---
tags: [gates, testing, shell]
---

# A check whose helper failed to `source` asserts nothing

Trap: `e2e-installer-gui-checks.sh` sourced its helper from the wrong path; `check` was undefined, every assertion was a no-op and the "127 failures" were bash's command-not-found status. No historical run was evidence.
Do instead: pin helper paths with a test; make "found nothing" a failure, not a pass. See `docs/ci-troubleshooting.md` §4 rows 27, 32.
