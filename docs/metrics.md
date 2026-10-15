# PR / build metrics

**Status: not yet implemented.** This file records the intent honestly and does not make it up.
There is no metrics pipeline here today.

## What already exists

- [`.github/green-criteria.yml`](../.github/green-criteria.yml) tracks
  snapshots of the status of each criterion over time (`status_<date>` fields).
  This is the closest thing to a trend line TunaOS has right now — see
  `docs/quality.md`.
- `.github/workflows/matrix-status.yml` and `weekly-boot-report.yml`
  produce point-in-time build/boot reports.

## What's missing

A real PR-acceptance metric (time-to-merge, revert rate, CI-failure rate by
category) would need a script. That script would read the GitHub API on a schedule and
write a report. None of that exists yet. If this becomes worth the work,
model it on `scripts/gen-matrix-status.py`, which already does the
equivalent aggregation for build status.
