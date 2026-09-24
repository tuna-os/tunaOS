---
tags: [testing, gates, ci]
---

# Do not skip, disable or weaken a failing test or gate to get green

Do not skip, xfail, `continue-on-error`, or loosen a failing test or gate to make a PR pass. Find the cause: a check that always fails is itself the bug, and a failure seen only on a developer machine can be a real defect. Blocking criteria in `.github/green-criteria.yml` must not be waved through; `tests/test_ci_contract.py` checks this.

Source: `AGENTS.md` ("A permanently-red check is a dead gate", "A test that fails only on developer machines..."); `.github/green-criteria.yml` header.
