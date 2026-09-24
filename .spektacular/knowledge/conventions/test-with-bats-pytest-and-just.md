---
tags: [testing, spektacular]
---

# Test with bats, pytest and `just`, not with the Go defaults

In the `test` and `verify` steps of `spektacular implement`, ignore the Go tooling that the step text suggests (`*_test.go`, testify, `make test`, `make lint`). tunaOS tests shell with bats in `tests/bats/`, Python and workflow contracts with pytest in `tests/`, and incident regressions in `tests/regressions/` (named `test_issue_<n>_*.py`, with a `Falsification:` line). Run `just fix && just check` and `just test`. When `just` is not installed, run its parts: shellcheck, the pinned shfmt, actionlint, bats, pytest and `scripts/run-ste-lint.sh`. A bats test that fails on a pristine `main` checkout too is not a regression; say so in the PR.

Source: `AGENTS.md` Quick Reference; `just/utilities.just`; `tests/regressions/README.md`; RFC 011 prototype (PR #2682).
