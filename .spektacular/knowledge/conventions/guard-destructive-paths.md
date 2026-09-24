---
tags: [shell, safety]
---

# Validate a path before `rm -rf`; make deletes conditional on the copy

Refuse empty and non-absolute paths before resolving them, refuse `/` and `$PWD` after, and never `rm -rf` on the strength of a `cp` whose exit status you did not check.

Source: `AGENTS.md` "Guard a path before you destroy it"; `docs/ci-troubleshooting.md` §4 row 39.
