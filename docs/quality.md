# Quality dashboard

TunaOS doesn't have a separate app for a quality dashboard. The quality signal
lives in [`.github/green-criteria.yml`](../.github/green-criteria.yml)
(prose companion: [`docs/GREEN-CRITERIA.md`](GREEN-CRITERIA.md)). That file is
the source of truth for what "green" means for a given (variant, flavor)
cell, and `tests/test_green_criteria.py` keeps it honest.

Each criterion in that file records:

- `enforcement` — `blocking` (a cell needs it for green status), `advisory`
  (measured and reported, does not block yet), or `unimplemented` (no
  automated assertion exists yet).
- a `status_<date>` history, so progress since the project raised the bar
  (`raised_on: 2026-08-17`) is measurable instead of remembered.
- which workflow asserts it (`asserted_by`), so a criterion always
  traces back to a real, runnable check instead of an aspiration.

The composite rule that makes the list mean something: a cell has green status only
if every `blocking` criterion has an affirmative, *current* result. Never-tested,
skipped, or stale evidence does not count as satisfied. See
`skills/check-green-criteria/SKILL.md` for how to read it when
you investigate a specific cell.
