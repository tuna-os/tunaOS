# Quality dashboard

TunaOS doesn't have a separate quality dashboard app — the quality signal
lives in [`.github/green-criteria.yml`](../.github/green-criteria.yml)
(prose companion: [`docs/GREEN-CRITERIA.md`](GREEN-CRITERIA.md)), which is
the source of truth for what "green" means for a given (variant, flavor)
cell, kept honest by `tests/test_green_criteria.py`.

Each criterion in that file records:

- `enforcement` — `blocking` (a cell cannot be green without it), `advisory`
  (measured and reported, not yet blocking), or `unimplemented` (no
  automated assertion exists yet).
- a `status_<date>` history, so progress since the bar was raised
  (`raised_on: 2026-08-17`) is measurable rather than remembered.
- which workflow actually asserts it (`asserted_by`), so a criterion always
  traces back to a real, runnable check rather than an aspiration.

The composite rule that makes the list mean something: a cell is green only
if every blocking criterion has an affirmative, *current* result — never
tested, skipped, or stale evidence does not count as satisfied. See
`.claude/skills/check-green-criteria/SKILL.md` for how to read it when
investigating a specific cell.
