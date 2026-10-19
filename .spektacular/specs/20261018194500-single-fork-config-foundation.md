---
created_date: "2026-10-18"
document_status: final
closed_date: "2026-10-18"
---

# Single fork config foundation

## Overview

Give a fork one owned YAML file for target, package and brand intent, with
asset references. Start with a review tool that preserves current builds.
Tracking issue: [#3433](https://github.com/tuna-os/tunaOS/issues/3433).

## Requirements

- Reject unknown keys, wrong types, duplicate YAML keys and stale source pins.
- Reuse the build config seam, flavor resolver, manifests and identity inputs.
- Define global, variant, desktop and cell precedence, ordered package intent,
  conflict errors and local asset paths.
- Emit all declared cells with their original build hold and route.
- Export stock inputs through the legacy seam without changing source values.
- Refuse fork intent in that export until the consumers exist.

## Acceptance criteria

Tests compare every expanded cell and route to the current source. The stock
export equals the whole legacy catalog and resolves every base image through
the existing shell entrypoint. Source hashes cover manifests, package scripts,
identity and committed assets. Tests reject conflicts, bad pins and bad assets.
These checks prove source/plan parity, not package transaction or image parity.

## Constraints

No workflow, Containerfile, package install or brand consumer change. No new
catalog of variants or packages. Keep disabled cells and all admission data.
Keep normal builds independent of Python and the new opt-in command.

## Technical approach

A Python/PyYAML tool validates a closed v1 contract. It derives a source receipt,
uses the shell build-config seam, calls the existing flavor resolver, and emits
JSON review data. JSON also serves as a stock-only YAML-compatible adapter.

## Success metrics

All phase 1 tests pass; unchanged old entrypoints still pass their tests. Record
aggregate checks and failures without claiming image qualification.

## Non-goals

No package transactions, brand application, target scheduling, publication,
custom overlay repair or automatic pin update. No architecture merge approval.

## Verification

Run pytest contract tests, Bats resolver tests, just fix, just check and just
test. Record remaining failures separately from the focused evidence.
