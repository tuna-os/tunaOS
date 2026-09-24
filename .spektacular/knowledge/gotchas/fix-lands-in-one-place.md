---
tags: [variants, build, shell]
---

# A fix applied to one Containerfile or code path misses the others

Trap: a guard added after an early `exit 0` in `40-services.sh` ran on dnf images only; greetd fixes reached live cosmic/niri/xfce but not installed systems; `01-workarounds.sh` runs for el10/ubuntu only.
Do instead: put cross-variant fixes in a script all six Containerfiles invoke, check it runs before the first `exit`, and ask "does this propagate?". See `docs/ci-troubleshooting.md` §4 row 26; `AGENTS.md` "Being invoked is not being reached".
