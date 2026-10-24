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

## Qualification reuse and first-failure contract

`scripts/qualification-evidence.py` is the shared fail-closed boundary for
qualification adapters. `schemas/qualification-reuse-v1.schema.json` defines
producer receipts, current inputs and reuse decisions. A producer names the
exact manifest and config digests, source and config receipts, consumed build
inputs, platform, tool versions, workflow run and artifact. Run and artifact URLs must agree with their numeric GitHub IDs.
Tags and partial receipts cause a rebuild. Changed build inputs, identities or platforms also cause a rebuild.
After review, refresh the source receipt in the same push as a change to build source.
Never edit the digest alone.

Harness inputs and tools name the assertions they affect. Their changes may
reuse the exact image bytes. The decision sets the affected assertions to
`not-run`. The new harness cannot use an old verdict.

Build inputs include installer, engine and overlay pins, config assets and
package sources. Keep the existing limits for artifact retention and size. The
contract does not upload artifacts. It does not extend retention or approve
new storage.

Collect the current inputs independently. Then verify them against a producer
receipt:

```sh
python3 scripts/qualification-evidence.py verify-reuse \
  --producer producer-receipt.json \
  --current current-inputs.json \
  --output reuse-decision.json
```

`schemas/qualification-report-v1.schema.json` is the public diagnostic
allowlist. Write each event as one JSON object on its own line. Keep execution
order. Then run:

```sh
python3 scripts/qualification-evidence.py report \
  --context qualification-context.json \
  --events qualification-events.jsonl \
  --output qualification-report.json
```

The context declares every required assertion and retained evidence URL.
Unreported assertions remain `not-run`; skipped and failed assertions remain
distinct. A Welcome screenshot is its own assertion and never changes
`install` or `target-reboot`. The report keeps the first failed event. A later
cleanup failure stays visible but does not replace the original cause.

Failed events use one of `product`, `harness`, `runner` or `unknown`. Each event
cites an evidence ID from the context. The tool never infers a product defect.
The `unknown` class remains `unknown`.

Use bounded identifiers for commands. Do not put raw argument vectors in the
report. The closed schema has no field for a message, raw log, environment,
host path, credential or installer user data.

The tool marks a bad event stream with a bounded `harness` /
`malformed-evidence` first failure. The report does not copy the bad contents.
The tool limits each report to 256 KiB. Any failed, skipped or not-run
assertion keeps `releasePass` false.

## Six-route package-addition evidence

Issue [#3802](https://github.com/tuna-os/tunaOS/issues/3802) requires built-image
proof for the EL10, Ubuntu, Debian, Arch, openSUSE and Gentoo Containerfile
routes. Source tests and package-manager containers do not satisfy that gate.
After the primary image-package consumer is integrated, use
`scripts/qualify-image-packages.py` against local images built from one exact
two-commit pair:

- The stock commit has an empty generated
  `build_scripts/lib/image-packages.tsv`.
- Its single-child modified commit changes only `tunaos.toml` and that generated
  adapter. The adapter contains one required, family-native addition for each
  selected variant.
- Every plan cell names a digest-pinned `baseImage`. Build that exact reference,
  including a resolved digest for upstream sources that are normally tags.
- Every route supplies stock base, modified base and modified desktop images.
  EL10 also supplies a modified overlay image. These roles specifically prove
  Gentoo's separate `system` and `desktop-build` placements, openSUSE's base
  placement, desktop inheritance and overlay inheritance.

The plan is a JSON object with `schemaVersion`, `platform`, full
`stockCommit`/`modifiedCommit` values and exactly six `cells`. Each cell names
`route`, `variant`, `package`, `baseImage` and `images`. An `images` value of
`null` records that family as `not-run`; it never passes the gate. Image records
contain the local `ref` and requested `flavor`.

```sh
python3 scripts/qualify-image-packages.py \
  --plan package-qualification-plan.json \
  --source "$PWD" \
  --output package-qualification-evidence
```

The verifier reruns the primary generated-adapter check and route resolver. It
then binds each result to the registry bytes of the pinned base, local image
manifest/config digests and `/usr/share/ublue-os/image-info.json`. The stock
image must have neither the package nor a package-addition receipt. Every
modified base, desktop and overlay image must contain the native package and an
exact `/usr/share/tunaos/image-packages.tsv` receipt.

Retain the output directory with the build logs. `report.json` records each
family as `passed`, `failed` or `not-run`; each route log and the source log
have SHA-256 values in the report. A failed family does not hide later family
results. Required-install failure, optional-missing handling, manager mismatch,
signed repository handling, existing-repository refusal, apt no-removal and
removal rejection remain source-level failure cases; run their primary F4
suite on the same source commit and retain that log beside this image evidence.

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

The opt-in preview uses `examples/fork/stock.template.yaml`. Initialize a new
strictly pinned config with `--init-template` before you resolve or build it.
Existing configs retain their reviewed pins and fail when source inputs change.
Initialization never refreshes an existing config. See
[FORK-CONFIG-PREVIEW.md](FORK-CONFIG-PREVIEW.md) for commands and supported intent.

## What completes the milestone

Document a fresh fork's steps and prerequisites, including config validation,
image destination, source pins, supported package changes and brand assets.
Attach immutable evidence for every stage on both reference families. Include
update and recovery instructions with their measured results. A second person
must be able to repeat the recipe without unpublished edits.

Use the linked issues and generated evidence for progress. This document sets
outcomes and dependencies; it does not grant a merge, release, route change,
new storage budget or artifact deletion.
