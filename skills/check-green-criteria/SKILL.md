# Check green criteria

Use this when asked whether a (variant, flavor) cell is actually green, or
why it isn't — "green" here means something specific, defined in
[`.github/green-criteria.yml`](../../.github/green-criteria.yml) (prose
companion: [`docs/GREEN-CRITERIA.md`](../../docs/GREEN-CRITERIA.md)).

## Steps

1. Read `.github/green-criteria.yml` — each criterion records its
   `enforcement` (`blocking`, `advisory`, or `unimplemented`) and a
   `status_<date>` history. A criterion whose result is skipped, never
   tested, or stale does **not** count as satisfied (`rule.never_tested_is_not_green`
   etc.) — don't treat silence as a pass.
2. Check `scope` blocks under criteria like `boots` and `parity` — a cell
   outside a criterion's scope isn't judged on it at all; that's a reviewed
   exclusion, not a gap.
3. Cross-reference against `tests/test_green_criteria.py`, which is what
   actually keeps this file honest — if the two disagree, the test is
   usually right and the YAML needs updating, not the other way round.
4. For a specific cell's live status, check the workflow named in that
   criterion's `asserted_by` field (e.g. `desktop-contract-sweep.yml` for
   `desktop`, `reusable-build-image.yml`'s Gate job for `boots`).

Never report a cell "green" from a "builds and promotes" result alone —
that's the weakest claim the pipeline can make (see the file's own header
comment for why: `tunaOS#858`, an image that shipped with no desktop at
all).
