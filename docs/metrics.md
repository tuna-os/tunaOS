# PR / build metrics

**Status: not yet implemented.** This file exists so we record the intent
honestly — there is no metrics pipeline here today.

## What already exists

- [`.github/green-criteria.yml`](../.github/green-criteria.yml) tracks
  snapshots of status per criterion over time (`status_<date>` fields).
  This is the closest trend line that TunaOS has now — see `docs/quality.md`.
- `.github/workflows/matrix-status.yml` and `weekly-boot-report.yml`
  produce point-in-time build/boot reports.

## What's missing

A real PR-acceptance metric (time-to-merge, revert rate, CI-failure rate by
category) would need a scheduled script. The script would read the GitHub
API and write a report — none of that exists yet. If this becomes worth a build,
model it on `scripts/gen-matrix-status.py`, which already aggregates build
status.
