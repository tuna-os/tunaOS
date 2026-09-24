---
tags: [gates, evidence, ci]
---

# A red cell can be stale evidence, not a live bug

Trap: matrix/LUKS cells show the last run's verdict; the bug may already be fixed on main.
Do instead: check the run date and commit against main before diagnosing; re-run. See `docs/ci-troubleshooting.md` §16.
