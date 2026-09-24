---
tags: [git, branching, porting]
---

# Land work on `main`; port fixes from other branches, adapted

`main` is the canonical branch. A fix that exists only on another line (e.g. `v4`) is ported to `main` as its own change, adapted to main's code, not blindly cherry-picked, and with its prerequisites.

Source: maintainer direction, 2026-09-24, recorded in `docs/rfc/rfc011-spektacular.md` (the tacklebox port for tunaOS#1893); `v4` and `main` have diverged (`git merge-base --is-ancestor origin/v4 origin/main` is false). Not yet written in `AGENTS.md`.
