---
created_date: "2026-09-24"
document_status: draft
project: tunaos
spec: 20260924185724-68c5afaf-tacklebox-commit-deadline
plan: 20260924185724-68c5afaf-tacklebox-commit-deadline
---

ISO builds of large desktops no longer fail when tacklebox commits the customized live image: the commit now gets 30 minutes instead of 10, and a malformed override fails loudly instead of being ignored. Any `TBOX_*` tacklebox setting a workflow exports now takes effect whether tacklebox runs as a host binary or as a container.

> Derived from project tunaos (local), spec/plan 20260924185724-68c5afaf-tacklebox-commit-deadline. See the project-level record for the full feature.

## What changed in this repo

- `scripts/lib/tacklebox.sh`: 1800 s default + validation for `TBOX_CUSTOMIZE_COMMIT_TIMEOUT`; exported `TBOX_*` forwarded into the container; knobs logged.
- `image-versions.yaml`: tacklebox pin `f3dd168` -> `ae93e9b`.
- `tests/bats/test_build_iso_tacklebox.bats`: 11 new cases; `tests/regressions/test_issue_1893_customize_commit_deadline.py`: new.
- `docs/TACKLEBOX-CONTRACT.md`, `docs/ci-troubleshooting.md` (row 42), `.github/workflows/weekly-desktop-screenshots.yml` (comment).

## Why

tunaOS#1893: commits of multi-GB desktop layers exceeded tacklebox's fixed 600 s limit on CI. main is the canonical branch and never received v4's fix.
