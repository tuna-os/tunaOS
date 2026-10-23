# Adoption observability audit

This is the reproduction and evidence guide for [#3056](https://github.com/tuna-os/tunaOS/issues/3056).
Use it to derive implementation coverage from the checkout under review. It is
not a live deployment inventory or an installation count.

## Reproduce source coverage

Run from the repository root:

```bash
python3 scripts/config.py generate
python3 scripts/generate-countme-allowlist.py --check
python3 -m pytest -q tests/test_countme_client.py tests/test_countme_images.py tests/test_countme_ci_boot.py
```

The first command generates the ignored compatibility matrix from `tunaos.toml`.
The image tests consume that matrix, execute `build_scripts/install-countme.sh`
in temporary roots for every declared image cell, and compare canonical metadata
and inherited reporter masks. They also check the final-copy step and category
allowlist equality. The client tests check for weekly report tries, opt-out, live
exclusions and installed VM eligibility with synthetic network boundaries.
These tests do not boot the published images or verify the effective systemd
state on every package-manager family and architecture.

For collector storage, concurrent updates, rollback and public suppression tests,
use the pinned toolchain described in [the collector README](../services/countme/README.md):

```bash
npm ci --ignore-scripts --prefix services/countme
npm test --prefix services/countme
npm run build --prefix services/countme
```

Keep valid synthetic reports on the local machine. A production report changes
adoption counts. Do not use a production POST as a health probe.

## Resolve conflicting historical claims

The issue says that nobody confirmed a backend and that RFC approval is still
open. Compare those claims with [ADR 0011](adr/0011-private-adoption-metrics.md),
which records the accepted publication decision, and the [plan's deployment evidence](../.spektacular/plans/20260927065823-privacy-respecting-countme/plan.md#production-deployment-evidence-2026-09-27).
Those records landed in [merged PR #2776](https://github.com/tuna-os/tunaOS/pull/2776).
They record a production deployment and its measured limits; they do not prove
current availability. `services/countme/wrangler.jsonc` declares the hostname,
D1 binding, collection switch and application logging controls. Configuration
alone does not prove the deployment of those settings or verify account-wide
policy.

The plan's unchecked phases 2.1 and 2.2 describe installed-artifact and full-boot
acceptance. They do not mean that the image integration remains incomplete. A
source contract that passes must not check off those stronger criteria.

## Evidence still required for rollout acceptance

Keep the acceptance checklist in the [countme plan](../.spektacular/plans/20260927065823-privacy-respecting-countme/plan.md#milestone-2-cover-every-installed-image)
as the owner of completion status. Attach measured artifacts there or to its
[tracker #2775](https://github.com/tuna-os/tunaOS/issues/2775):

- Final published base, desktop and overlay identities and effective unit/mask
  state for supported families and architectures.
- Live and CI boot captures against a synthetic collector, with zero requests.
- Installed guests with correct categories and the weekly report behaviour.
- Upgrade and image-switch pilot evidence that keeps opt-out, administrator
  masks and weekly state.
- Failure isolation when the collector is unavailable.
- Account-owner verification of logging, provider retention and spend controls.
  ADR 0011 explicitly records that account-wide inspection was unavailable.

Only the account owner can verify account policy; a Worker configuration or an
accepted-report cap does not show it. This audit does not authorize cloud
changes or a new rollout.

## Adoption snapshots remain a separate measure

[ADOPTION-METRICS.md](../ADOPTION-METRICS.md) owns the monthly acquisition and
community snapshot scope under [#1174](https://github.com/tuna-os/tunaOS/issues/1174).
Track [PR #3605](https://github.com/tuna-os/tunaOS/pull/3605) for the public
baseline and the monthly snapshot work; do not duplicate that work here.
Release downloads, site visits and weekly countme reports have different
populations. Weekly reports are estimates of participation, not unique people,
exact installs or retention. Preserve missing and suppressed values; do not
convert them to zero.
