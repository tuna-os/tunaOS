# Deliver a fork-owned desktop

Epic: [#3474](https://github.com/tuna-os/tunaOS/issues/3474).

## Outcome

A user can fork TunaOS, edit one config, and install their own branded
Yellowfin or Grouper desktop with repeatable documented steps.

Start with Yellowfin (RPM) and Grouper (APT), GNOME on linux/amd64. This is a
reference scope, not a support claim for other cells. Keep the existing catalog,
platform limits and admission holds. A green source test does not prove that an
image boots or installs.

R2 secrets (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`, `R2_BUCKET`) are
TunaOS's own bucket and are not required for a fork. When they are empty, an R2
upload, prune or audit step does not call R2. The step does not run, or it stops
before the first R2 call (`tests/test_r2_optional_for_forks.py`).

## Deliver in this order

1. **One config and an explanation.** [RFC 013](rfc/rfc013-single-fork-config.md)
   and [#3433](https://github.com/tuna-os/tunaOS/issues/3433) own brand settings,
   package intent, target selection and image destination. Validate before
   mutation. Explain where each effective field came from. Keep strict source
   pins; a changed source needs review before the user accepts a new pin.
2. **Two complete journeys.** [#3474](https://github.com/tuna-os/tunaOS/issues/3474)
   owns the customized Yellowfin/RPM and Grouper/APT journeys. Reuse only matching
   immutable media evidence from [#3470](https://github.com/tuna-os/tunaOS/issues/3470).
   The superseded preview-config #3445 and stock native installs cannot qualify a
   new primary-TOML source/config/image combination. Prove build, boot, login,
   visible brand and actual installation. Detach the install media, boot the
   target disk, then prove update and recovery. Record every stage separately.
3. **Evidence for each exact image.** Extend the generated reports in
   [#3381](https://github.com/tuna-os/tunaOS/issues/3381). Bind the verdict to
   image digest, variant, desktop, platform, config/source receipt, tools and
   test time. Reject expired, absent or skipped evidence. Reject mismatches.
4. **Shared contracts.** Issue #3475 owns the schema list and common
   valid/invalid fixtures in [FORK-CONTRACTS.md](FORK-CONTRACTS.md). They cover
   brand settings, packages, image identity and installer inputs. Reuse these
   contracts. Put frontend changes in their repositories. Test the same fixture
   version there. State backend differences.
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
policy. A broad Mature/Beta label must not substitute for exact-image evidence.

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

## Materialize a customized reference without repeating conformance

The accepted config-only campaign is image inspection evidence, not retained
image bytes. For example, run `41217053069` at source
`2311ad923fa7701edf5b0400ac99f7d1c4bbaab2` retained only its plan and report in
artifact `13049438987` (53,633 bytes; artifact digest
`sha256:8fb85dc41184f53973cfcbe5f8a40f40fff905a4e6dd3249ff36e12cf496f288`).
The plan's local customized commit is
`a4674fff38ec2a95e5224db07de87711edd023fd`. Its Yellowfin desktop manifest
`sha256:a4b576ae6c534d06b8cc6b134cf9df9dce2616eef4c9aee18a51a14a7b520a07`
is an observed historical identity, not a downloadable customized image. A
report or a `localhost/` tag cannot supply missing image layers. Preserve that
eight-image pass; do not rerun it to get lifecycle inputs.

After review and explicit build approval, use the manual
`config-reference-materialization.yml` workflow. It builds **one** customized
image with GNOME for `linux/amd64`. `family=rpm` selects Yellowfin;
`family=apt` selects Grouper. Both Containerfiles build their own `base-no-de`
stage in the GNOME target; a separate base output or stock build is unnecessary.
The unchanged config-only helper still prepares the complete eight-image plan.
The materializer selects `modifiedDesktop`; it does not narrow that
conformance gate or label the new build a fresh conformance pass.

Before a Grouper request, review the APT verifier and code that keeps the
kernel configuration. They must exist in the selected source.
The materializer runs this verifier inside the exact image, without a network
or host privileges.

It must find the kernel, configuration and initramfs. It also checks the backend
and the checker for the brand. A failure stops retention. These checks do not
prove a boot or visible brand.

The build needs `40GiB` free on each source, output, and container-store disk.
For a sparse loop device, it also checks the file on the real disk.
The export needs that same free space **plus** the size of two complete archives
and the largest layer. Sizes come from the actual immutable manifest, with
bounds for tar headers, padding, and JSON.

The two copies account for the temporary OCI layout that Skopeo makes before
it writes the archive. Both temporary files and the archive use the checked
output disk. The archive must stay within its calculated bound. Insufficient
space stops the job, not the safety check. The workflow does not remove layers
to make an image fit.

The workflow uses the current build interface to pass these flags to Buildah:
`--isolation=oci --memory=8g --memory-swap=8g --cpu-period=100000 --cpu-quota=200000`.
This requests `8GiB` for memory and `8GiB` for memory with swap.
Each container can use at most two CPUs. An unsupported control stops the job.
The workflow does not use `chroot`.

The receipt keeps the request for limits separate from available VM memory and CPUs.
The runner writes this receipt and prints it before the build.
Any failure in that pipe stops the build step.
Kernel enforcement remains `not-observed` until a measurement proves it.
The `300`-minute build and `360`-minute job bounds do not change.
The job runs on a hosted runner, not on the local machine.

Local builds and proof still need the existing free-space floor,
`/tmp/tuna-local-build.lock` and `/tmp/tuna-local-proof.lock`.
The existing `8GiB`, `MemorySwapMax=0`, and `CPUQuota=200%` limits still apply.
This change does not approve any local build.

For one approved Yellowfin build, set `REVIEWED_SHA` to the exact reviewed
40-character head of `main`. GitHub's
[dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
uses a branch or tag as its reference. The workflow compares the actual commit
against `reviewed_source_sha` before any build; a branch race fails closed.

```sh
gh workflow run config-reference-materialization.yml --repo tuna-os/tunaOS \
  --ref main -f reviewed_source_sha="$REVIEWED_SHA" -f family=rpm
```

Request Grouper separately with `-f family=apt` only after the parent reviews
its prerequisites. These commands do not grant permission to dispatch.
The workflow refuses a source mismatch between its reviewed SHA and its checkout.
It does not build ISOs, run guests, log in to a registry, push, sign or publish.

The 30-day run artifact retains:

- `reference-desktop.oci.tar`, a copy by the immutable ID from storage after
  inspection, with no manifest change or tag fetch;
- `materialization.json`, with fresh source/config/base/manifest/config-blob
  identities, archive SHA-256/size, and every runtime stage `not-run`;
- the original `config-only-image-plan.json`;
- `customized-source.bundle`, which keeps the customized commit. Its Git
  prerequisite is the exact stock commit from review.

Record the run ID, `run_attempt`, artifact ID/digest and SHA-256 of the receipt.
Do not substitute a historical digest for the identity of a new build.

Before use, compare the downloaded receipt with its independently recorded hash.
Verify the archive size and SHA-256 with a stream before the tar parser reads headers.
Then check every referenced blob without file extraction. The parser cannot
allocate from a PAX length until the archive bytes match that receipt:

```sh
python3 scripts/config-reference-materialization.py verify \
  --receipt materialization.json --archive reference-desktop.oci.tar \
  --receipt-sha256 "$RECORDED_RECEIPT_SHA256"
```

### Media and lifecycle admission remain separate

An OCI archive from this step has no admission to the strict ISO route.
The existing `build-iso-tacklebox.sh` route derives an offline payload
reference through the configured published destination; it does not expose a
reviewed retained-archive-to-immutable-payload interface. Do not retag these
customized bytes as a public TunaOS image or substitute a registry fallback.

In iso-builder, `scripts/plan-full-matrix.py` admits only `only=skipjack-gnome`.
The mode pair must be `plain` with no diagnostic flag, or `luks` with the
diagnostic flag. The approved TunaOS harness
`c1dfc3ddf08ea6152b2be716dfe8674b57116c5a` does not change that admission.
Neither `only=yellowfin-gnome` nor a customized image under a Skipjack label
meets these rules. Do not merge or reuse held #3431 to bridge this boundary.

There is **no authorized guest command for customized media**.
The native consumer needs review first. It must keep the exact manifest/config
identity from the archive through the offline store and installer recipe.
Custom media also need admission and exact receipts for the media and tools.

Only then ask the parent to approve a bounded campaign on the hosted runner.
Boot/login, visible brand, offline GUI installation and target boot without
the ISO still need evidence. A Welcome page is not an install receipt.

Update/recovery also need two distinct approved images, A and B, from a reachable
authorized source. They need immutable identities. Only Skipjack/GNOME is in
the scope of `installed-lifecycle-pilot.py`. Do not relax it or claim a
Yellowfin/Grouper A→B→A result. The owner of #3801 must approve an isolated
publish step. A retained archive, source receipt, stock install or successful
materialization cannot replace those update/recovery receipts.


## Six-route package-addition evidence

Issue [#3802](https://github.com/tuna-os/tunaOS/issues/3802) needs built-image
proof for the EL10, Ubuntu, Debian, Arch, openSUSE and Gentoo Containerfile
routes. Source tests and package-manager containers do not satisfy that gate.
After the integration of the primary image-package consumer, use
`scripts/qualify-image-packages.py` against local images built from one exact
pair of commits:

- The stock commit has an empty generated
  `build_scripts/lib/image-packages.tsv`.
- Its single-child modified commit changes only `tunaos.toml` and that generated
  adapter. The adapter contains one required, family-native addition for each
  selected variant.
- Every plan cell names a digest-pinned `baseImage`. Build that exact reference,
  including a resolved digest for upstream sources that are normally tags.
- Every route supplies images for the stock base, the modified base and the modified desktop.
  EL10 also supplies a modified overlay image. These roles specifically prove
  Gentoo's separate `system` and `desktop-build` placements, openSUSE's base
  placement, desktop inheritance and overlay inheritance.

The plan is a JSON object with `schemaVersion`, `platform`, full
`stockCommit`/`modifiedCommit` values and exactly six `cells`. Each cell names
`route`, `variant`, `package`, `baseImage` and `images`. An `images` value of
`null` records that family as `not-run`; it never passes the gate. Image records
contain the local `ref` and requested `flavor`.

The verifier needs a clean checkout, including untracked files. Keep both
the plan and the evidence directory out of the source tree: use the ignored
`output/` directory, or any path outside the checkout.

```sh
python3 scripts/qualify-image-packages.py \
  --plan output/package-qualification-plan.json \
  --source "$PWD" \
  --output output/package-qualification-evidence
```

The verifier reruns the primary generated-adapter check and route resolver. It
then binds each result to the registry bytes of the pinned base, local image
manifest/config digests and `/usr/share/ublue-os/image-info.json`. The stock
image must have neither the package nor a package-addition receipt. Every
modified base, desktop and overlay image must contain the native package and an
exact `/usr/share/tunaos/image-packages.tsv` receipt.

Every role, including the overlay, must record the pinned base as its
`base-image`. The overlay's `90-image-info.sh` sources `lib.sh`, which restores
that field from the inherited `image-info.json` of the desktop stage. The
metadata of an image cannot prove the modified desktop parent of the overlay. A rechunked or
multi-instruction build leaves no parent that Podman storage can use. The build
of the overlay from the `modifiedDesktop` reference of the plan binds the
parent, and the retained build logs must show that build.

Retain the output directory with the build logs. `report.json` records each
family as `passed`, `failed` or `not-run`. Each route log and the source log
have SHA-256 values in the report. A failed family does not hide the results of
later families.

These cases remain source-level failures:

- a required install that fails;
- an optional package that is missing;
- a manager mismatch;
- a signed repository;
- an existing repository that the tool refuses;
- apt no-removal and removal rejection.

Run their primary F4 suite on the same source commit and retain that log beside
this image evidence.

### Running the harness in CI

`.github/workflows/qualify-image-packages.yml` is manual only. It has no
schedule and no other trigger, `contents: read`, no secret and no publish step.
It runs one matrix leg for each route, and each leg has its own runner. A leg
uses `just build` for the stock base, the modified base and the `gnome` desktop.
On EL10 it also builds the `gnome-hwe` overlay.

`scripts/package-qualification.py prepare` makes the commit pair in the job
workspace and never pushes it. The stock commit pins any mutable `base_image` to
its current digest. The modified commit adds `tree` (`app-text/tree` on Gentoo)
to the packages of each variant and regenerates the adapter. The packages come
from `tests/fixtures/package-qualification-cells.json`.

The harness then runs as root over the images of that route. The other five
cells are `not-run` in the report of that leg, so `releasePass` is `false` in
every leg. A leg passes when `package-qualification.py gate` finds its own route
`passed`. The six legs together are the six-route result. Each leg uploads
`package-qualification-<route>` with `report.json`, the route logs, the build
logs and the plan.

```sh
gh workflow run qualify-image-packages.yml --ref <branch>
gh workflow run qualify-image-packages.yml --ref <branch> -f routes='["ubuntu"]'
```

A fork keeps its own `tunaos.toml`. A route fails fast if the fork already
defines `[variants.<variant>.packages]` for a fixture variant.

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

The YAML preview interface (`resolve-fork-config.py`, `prepare-fork-config.py`,
`examples/fork/*.template.yaml` and its prepared-context consumers) no longer
exists since [#3807](https://github.com/tuna-os/tunaOS/issues/3807). A fork edits `tunaos.toml`
and asset files only. An old config converts with
`python3 scripts/config.py migrate-fork-config --legacy OLD.yaml`; see
[PRIMARY-CONFIG-MIGRATION.md](PRIMARY-CONFIG-MIGRATION.md#migrating-a-legacy-fork-config).
Receipts from the retired preview do not qualify a primary-TOML build.

## What completes the milestone

Document a fresh fork's steps and prerequisites, including config validation,
image destination, source pins, supported package changes and brand assets.
Attach immutable evidence for every stage on both reference families. Include
update and recovery instructions with their measured results. A second person
must be able to repeat the recipe without unpublished edits.

Use the linked issues and generated evidence for progress. This document sets
outcomes and dependencies; it does not grant a merge, release, route change,
new storage budget or artifact deletion.
