# PR / build metrics

**Status: not yet implemented.** This file exists so the intent is written
down honestly rather than fabricated — there is no metrics pipeline here
today.

## What already exists

- [`.github/green-criteria.yml`](../.github/green-criteria.yml) tracks
  per-criterion status snapshots over time (`status_<date>` fields), which
  is the closest thing to a trend line TunaOS has right now — see
  `docs/quality.md`.
- `.github/workflows/matrix-status.yml` and `weekly-boot-report.yml`
  produce point-in-time build/boot reports.

## What's missing

A real PR-acceptance metric (time-to-merge, revert rate, CI-failure rate by
category) would need a script that reads the GitHub API on a schedule and
writes a report — none of that exists yet. If this becomes worth building,
model it on `scripts/gen-matrix-status.py`, which already does the
equivalent aggregation for build status.
