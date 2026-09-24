---
tags: [tacklebox, pins, workflows]
---

# A tacklebox SHA hardcoded in a workflow stops tracking the floor

Trap: `luks-e2e.yml` pinned `TACKLEBOX_SHA: fd95174`; the tracked pin moved on for a runner fix and every cell of the monthly sweep failed at "Build dev ISO". Surprising because the old SHA was the documented floor.
Do instead: pin only in `image-versions.yaml`; let `scripts/lib/tacklebox.sh` fall back to it. See `docs/ci-troubleshooting.md` §4 row 22.
