# Deliver a fork-owned desktop

Epic: [#3474](https://github.com/tuna-os/tunaOS/issues/3474).

## Outcome

A user can fork TunaOS, edit one config, and install their own branded
Yellowfin or Grouper desktop with repeatable documented steps.

Start with Yellowfin (RPM) and Grouper (APT), GNOME on linux/amd64. This is a
reference scope, not a support claim for other cells. Keep the existing catalog,
platform limits and admission holds. A green source test does not prove that an
image boots or installs.

## Deliver in this order

1. **One config and an explanation.** [RFC 013](rfc/rfc013-single-fork-config.md)
   and [#3433](https://github.com/tuna-os/tunaOS/issues/3433) own brand settings,
   package intent, target selection and image destination. Validate before
   mutation. Explain where each effective field came from. Keep strict source
   pins; a changed source needs review before the user accepts a new pin.
2. **Two complete journeys.** Use the native reference lane in
   [#3445](https://github.com/tuna-os/tunaOS/pull/3445). Prove build, boot, login, visible brand and actual installation.
   Detach the install media, boot the target disk, then prove update and recovery. Record each stage as
   passed, failed or not run. Keep one investigation active in native CI.
3. **Evidence for each exact image.** Extend the generated reports in
   [#3381](https://github.com/tuna-os/tunaOS/issues/3381). Bind the verdict to
   image digest, variant, desktop, platform, config/source receipt, tools and
   test time. Reject expired, absent or skipped evidence. Reject mismatches.
4. **Shared contracts.** [#3475](https://github.com/tuna-os/tunaOS/issues/3475)
   tracks schema owners and common valid/invalid fixtures for brand settings,
   packages, image identity and installer inputs. Reuse current contracts.
   Put frontend changes in their own repositories and test the same fixture
   version there. Keep differences in backend capabilities explicit.
5. **Fast tests and useful failures.**
   [#3476](https://github.com/tuna-os/tunaOS/issues/3476) tracks how to reuse verified images and invalidate results.
   It also defines bounded reports for the first failure. Separate
   product, harness, runner and unknown failures. Use allowlisted fields;
   exclude secrets, installer user data and private host paths.
6. **Small, shipped outcomes.** Review and integrate the smallest prerequisite
   before scope expands. [#3470](https://github.com/tuna-os/tunaOS/issues/3470)
   owns delivery of browser ISOs. Cut over one qualified target at a time with
   browser/native parity receipts. Keep existing downloads for every other
   target and retain existing artifacts. Deployment needs its own approval.

## Evidence stages are separate from lifecycle labels

These are acceptance requirements for the generated report, not current image
status. [VARIANT-LIFECYCLE.md](../VARIANT-LIFECYCLE.md) still owns lifecycle
policy. A broad Stable/Beta label must not substitute for exact-image evidence.

- **Experimental:** not yet qualified by this journey.
- **Build-tested:** the exact image has a successful build and artifact checks.
- **Boot-tested:** that image also has the required boot/session evidence.
- **Release-qualified:** all gates required for release pass. These include actual
  install, target-only reboot, update and recovery for the declared scope.

Keep the result of each gate alongside the summary stage. A successful
installer launch or Welcome page is not installation. A harness error is not
proof of a product defect and cannot produce a release pass. A moved tag invalidates the affected verdict until the next test.
A change to an input used by that test does the same.

## Dependency and review boundaries

The compatibility foundation is [#3434](https://github.com/tuna-os/tunaOS/pull/3434)
and [#3436](https://github.com/tuna-os/tunaOS/pull/3436). The consumer sequence is
[#3439](https://github.com/tuna-os/tunaOS/pull/3439),
[#3440](https://github.com/tuna-os/tunaOS/pull/3440), then
[#3443](https://github.com/tuna-os/tunaOS/pull/3443). Package safety extends through
[#3444](https://github.com/tuna-os/tunaOS/pull/3444),
[#3446](https://github.com/tuna-os/tunaOS/pull/3446),
[#3449](https://github.com/tuna-os/tunaOS/pull/3449) and
[#3453](https://github.com/tuna-os/tunaOS/pull/3453). Package removal proof is
separate from the baseline branded-install outcome.

These links identify who owns each dependency. They are not a live status table.
Read each PR's current base, exact-head checks and evidence before integration.
Do not merge the stack as a unit on the strength of a source-test pass.
Reconcile the shared catalog with [#3431](https://github.com/tuna-os/tunaOS/pull/3431)
and its parent [#3143](https://github.com/tuna-os/tunaOS/pull/3143), and do not add another catalog. Keep one active change per shared contract surface.

The foundation recipe uses `examples/fork/stock.yaml`. The consumer preview
introduces `stock.template.yaml` and explicit initialization. Use the commands
from the checked-out revision. Do not copy a preview command into the shipped
recipe before its prerequisite lands. Both recipes keep the existing strict pin until the user reviews a change.

## What completes the milestone

Document a fresh fork's steps and prerequisites, including config validation,
image destination, source pins, supported package changes and brand assets.
Attach immutable evidence for every stage on both reference families. Include
update and recovery instructions with their measured results. A second person
must be able to repeat the recipe without unpublished edits.

Use the linked issues and generated evidence for progress. This document sets
outcomes and dependencies; it does not grant a merge, release, route change,
new storage budget or artifact deletion.
