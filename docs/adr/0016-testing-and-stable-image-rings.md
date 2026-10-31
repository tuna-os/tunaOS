# ADR 0016: `:testing` and `:stable` image rings

- Status: accepted
- Date: 2026-10-30
- Approval: the maintainer approved every recommendation of RFC 018 on 2026-10-30 ([#4154](https://github.com/tuna-os/tunaOS/issues/4154#issuecomment-6534034193)).
- RFC: [RFC 018](../rfc/rfc018-testing-stable-rings.md)
- Issue: [#4154](https://github.com/tuna-os/tunaOS/issues/4154)
- Supersedes: the Weekly and LTS tiers of [ADR 0006](0006-date-based-versioning.md). No workflow ever wrote them. Date-based tags stay.

## Context

The Promote job copies each verified build onto the bare `:<flavor>` tag in
the same run that built it. Every install, every doc and every weekly ISO
tracks that tag. Nothing stands between a regression that CI cannot see and
all users.

## Decision

- There are two rings and no LTS.
- **`:<flavor>-testing`** is the gated nightly: every build that passes the
  boot, desktop and Asahi gates.
- **`:<flavor>`** (bare), with its arch tags and alias images, is `:stable`.
  It moves only through `promote-stable.yml`, daily at 06:00 UTC, by digest,
  to the newest dated tag that meets all of these:
  - it has soaked for at least `soak_days` (default 3, set per variant);
  - no open `release-blocker` issue names the cell;
  - the latest desktop-contract sweep for the cell passed;
  - promotion honours every `Soak-After: <N>d` trailer in its commits.
- The ungated build output that the gates read is **`:<flavor>-candidate`**.
- Dated tags (`:<flavor>[-<arch>]-YYYYMMDD`) record when a digest entered
  `:testing`. They are the soak clock and the rollback anchors.
- Rollback repoints `:stable` to an earlier dated tag. It needs a reason.
- The weekly ISOs build from `:stable`.
- The variant maturity stage "Stable" becomes "Mature", so "stable" names
  only the ring.

## Consequences

- Default users get an image only after it has soaked. People who want each
  day's build switch to `-testing`.
- The rollout has four phases. Users see no change until phase 3, which
  follows a week of dry-run promotion (RFC 018, Rollout).
- `VERSIONING.md`, `docs/IMAGE-TAGS.md`, the rollback runbook and the
  "stable version" text in `reusable-build-image.yml` change in phase 3.
- The SDLC ledger item HIVE-6 / TUNA-3 is this decision ([#4072](https://github.com/tuna-os/tunaOS/issues/4072)).
