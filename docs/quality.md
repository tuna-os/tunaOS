# Quality dashboard

TunaOS does not have a separate quality dashboard. The quality signal lives in [`.github/green-criteria.yml`](../.github/green-criteria.yml) (prose companion: [`docs/GREEN-CRITERIA.md`](GREEN-CRITERIA.md)). That file is the source of truth for green status for each cell. `tests/test_green_criteria.py` verifies this state.

Each criterion in that file records:

- `enforcement` — `blocking` (a cell needs this to pass), `advisory` (measured and reported, but not required), or `unimplemented` (no automated test exists yet).
- a `status_<date>` history, so the team can measure progress since the date of change (`raised_on: 2026-08-17`).
- which workflow asserts it (`asserted_by`), so a criterion always traces back to a real check.

A composite rule sets the requirements: a cell passes only when each `blocking` criterion has a current affirmative result. Never-tested, skipped, or stale evidence does not count. See `skills/check-green-criteria/SKILL.md` to inspect a specific cell.
