# Bounded ISO coverage candidate — not active

This candidate adds an inventory, a bounded schedule, receipts, and diagnostic tests.
It reconstructs evidence from authenticated Actions artifacts.
The [approved canary](https://github.com/tuna-os/tunaOS/actions/runs/39951111670) passed at `fb71f4b4`.
It showed a legacy install with LUKS and a passphrase boot, not strict GUI or production coverage.
The later TCG fallback has source tests only; no second canary was run.
This work does not change repository variables, remote state, or existing schedules.

## Scope and cadence

`scripts/plan-iso-coverage.py --date 2026-10-23` uses the reviewed parser for `tunaos.toml`.
It does not construct a Cartesian product.
The baseline includes desktop cells with `build_image`, even without `build_iso`.

Browser builds consume images. The baseline excludes headless and overlay flavors.
It respects explicit `luks_e2e=false` admissions.
The report shows other architectures and image-only cells without a coverage claim.

The initial tree at `bacce9ed` has these counts:

- 53 admitted cells for baseline amd64 base × DE installs.
- 11 Tuna cells for images only.
- 25 additional cells for arm64 installs.
- 9 additional cells for amd64/v2 installs.

Regenerate the inventory after configuration changes. These counts do not show test passes.
The inventory includes Pantheon. It excludes GNOME on disabled Flounder.

The fixed rotation selects each baseline cell once in 28 days, at most two per day.
More than 56 cells causes an error and needs a budget review.
The execution adapter instead selects the oldest run first.
Fresh cells need no repeat. Failed, absent, and stale cells have equal access to the queue.
A source revision does not reset queue age or prevent later cells from a turn.

The limit of 28 days describes capacity with stable inputs, **not an outage-proof freshness SLA**.
The report shows absent or stale coverage after missed runs and input changes.

The daily workflow at 04:15 UTC stays inactive until an authorized maintainer sets `TUNAOS_ISO_COVERAGE_ENABLED=true`.
Manual dispatch defaults to a plan only. This candidate does not set the variable.

At most two calls run in parallel.
Receipts for completed cells and conservative reservations after failure consume the same two-cell budget per UTC day.
Another dispatch does not reset that budget.
The caller and callee refuse to rerun execution. Use a new authorized dispatch after diagnosis.

## Cost and migration

The post-build workflow estimates 45–60 runner-minutes per legacy cell for a dev ISO, install, and reboot.
Thus 53 cells cost about 40–53 runner-hours per cycle.
Two cells per night would cost about 90–120 runner-minutes at that rate.
But the timeout is 240 minutes per cell.
**The hard ceiling is 480 runner-minutes, plus the plan and setup costs.**
Gentoo builds can take much longer than the estimate.
These estimates do not describe strict plain+LUKS GUI qualification.

The monthly sweep for LUKS covers 110 graphical amd64 cells, with overlays.
Other schedules test TPM each quarter, Marlin KDE after builds, and five Marlin desktops each week.
The weekly installer-smoke cron stays in comments.
Before activation, review and prove which monthly baseline tests the new schedule can replace.
Keep the other overlay cells (initially 57) and quarterly hardware policy.
Do not replace all 110 cells with 53 or run duplicate full sweeps.

## Distinct evidence layers

| Layer | Candidate behavior | Does not prove |
|---|---|---|
| PR contracts | Read-only inventory/API/receipt/workflow tests | An ISO booted |
| Affected cells | Conservative path map, bounded samples, full deferred list | Unselected cells passed |
| Baseline rotation | Legacy `luks-e2e.yml` backend install/passphrase reboot | Plain GUI install or exact shipped ISO qualification |
| Strict GUI | Separate schema: offline/UI/detached cold+warm boot/identity and mode-specific layout/unlock checks | Other desktop drivers exist or passed |
| Diagnostic canary | One approved exact-head Skipjack/GNOME legacy run | Production coverage or a strict GUI verdict |

The production scheduler runs **legacy LUKS only**.
Inventory `required_modes: [plain,luks]` describes the desired strict contract. It does not claim that both modes ran.
Strict GUI remains unqualified.
A process, screenshot, image boot, or successful workflow alone does not prove a cell passed.

## Measured producer and durable evidence

Opt-in capture measures the offline platform manifest that the guest selects.
It also measures the ISO bytes and the fisherman binary that the workflow injects.
The legacy workflow builds this backend for the test. Its identity is not the embedded GUI bundle.
Exact markers for install start, encrypted disk, and passphrase boot combine with the install-step outcome to set the checks.

A pass cannot hide a later failure.
Absent inputs can have null digests only in fail/infra receipts.
The producer does not invent SHA256 values or pass receipts.

Small immutable receipts and plans have 90-day artifact retention.
Large legacy videos and logs keep their 14-day retention.
The receipt does not claim that those large archives remain available.
Local ledger helpers support locks and atomic fsync/replace operations.
Production reconstruction uses GitHub Actions artifacts, not a new mutable service, credential, R2 grant, or external datastore.

The GET-only adapter resolves the allowlisted outer workflow to an API ID.
It checks repository, main branch, head, and `run_attempt` identities.
It verifies the archive SHA256 and size, rejects unsafe members in ZIP files, and validates the receipt schema.
The adapter removes GitHub credentials from cross-origin artifact redirects.
Lookup uses contents/actions read. Bounds are:

- 200 runs and 2,000 artifacts.
- 1 MiB per archive.
- Ten historical `run_attempt` lookups per run.
- 20 jobs for proof that a run did no work.
- A 300-second transport budget inside a 15-minute plan job.

If history is partial, malformed, or expired, execution stops with diagnostics, not an optimistic green report.

Authenticated plans establish which cell receipts to expect.
A failed, cancelled, or timed-out run can lack a receipt.
In that case, the authenticated plan and metadata from the terminal API establish an infra **reservation**, not qualification.
All checks are false and measured digests are null. The origin is `api-plan-terminal-run`.

This record does not prove that a test started. It preserves queue age and the budget count.
A successful run without an expected receipt remains incomplete.
The importer ignores a gated-off run only if the bounded results from the API prove all jobs skipped and no steps ran.

Historical reruns need separate windows from the authenticated API.
They count toward queue age and quota, never freshness.

## Freshness and input changes

Freshness needs an exact stage, mode, source SHA, source digest, media digest, installer digest, and workflow SHA.
A newer failure or invalid or contradictory record in the same lane cannot revive an older green result.
Absent or expired evidence stays absent. The inventory cannot expand through unknown receipt IDs.
Removed cells stay in history.

Before a new build, its media digest does not exist.
An unresolved cell can receive a bounded build to **measure** its inputs but remains unqualified.
Only an authenticated capture that matches the desired source and workflow establishes the measured media identity.
This evidence describes a tested snapshot.
It does not prove that an upstream tag or the current public ISO still has those bytes.

The CLI accepts `--receipts ledger.json --expected-inputs expected.json --now UTC_TIMESTAMP` for local assessment.
Resolve expectations independently; do not trust an arbitrary JSON map.
Production `collect-iso-coverage.py` accepts measurements only after API/provenance verification and current-main revision checks.
It excludes PR and diagnostic artifacts by workflow, branch, name, and provenance, regardless of their own status claims.

## Changed-path selection

Repeat `--changed-path PATH` for a PR diff.
Desktop adapters and manifests select that desktop. Variant build workflows select that base.
Shared installer/config changes, runtime checkpoint YAML, and unknown paths affect all baseline cells.

The planner selects at most two diverse representatives.
It lists every other ID in `changes.deferred` with explicit overflow.
This sample does not qualify all changed cells.
Documentation and unit-test-only changes stay in cheap checks.
Explicit `--cell` rejects invalid or unadmitted cells and overflow.

## Premerge tests without write tokens

`iso-coverage-checks.yml` runs cheap tests on pull requests with contents read only.
It does not install an OS or use `pull_request_target`.

Before merge, an authorized maintainer can approve the exact head of a reviewed internal PR, after user approval.
Add the label `iso:<full-40-character-head-sha>`.
`iso-coverage-canary.yml` handles only a `pull_request:labeled` event that matches that head.
Pushes and synchronize events do not retrigger it. A changed head does not match the old label.
The workflow excludes forks.

This mechanism avoids the default-branch prerequisite of a new manual-dispatch workflow.
After the workflow exists on main, explicit dispatch with `execute=true` and a source SHA with exact approval is also available.

The canary uses contents read only, no inherited secrets, no publisher callee, and no scheduled trigger.
Its outer limit is 120 minutes.
The helper fixes Skipjack/GNOME, verifies checkout identity, and reuses `just iso` and `iso-e2e.sh --luks`.
Its artifacts use the prefix `iso-coverage-diagnostic-*` and cannot enter production coverage.
Use this path to verify guest skopeo, measured hashes, marker capture, and actual artifact shape **before main merge or production activation**.
A diagnostic pass is not a production receipt.

## GUI expansion still required

There are five app families. GNOME/Pantheon share `org.bootcinstaller.Installer`.
KDE, COSMIC, niri, and Xfce use distinct `org.tunaos.Installer*` frontends.
Pantheon also has separate LightDM/session geometry. The selector for native overlays rejects it.
A shared app ID does not prove screenshots or coordinates work for both desktops.

Proposed representatives run in sequence within the same budget:

- Skipjack/GNOME, Marlin/KDE, Grouper/COSMIC, Sailfin/niri.
- Flounder/Xfce, Gurnard/Pantheon, Guppy/GNOME, Hummingbird/GNOME.

Keep actual welcome, encryption, summary, progress, done, and failure frames. Then build adapters from these measurements.
Do not call the GNOME driver universal.
First complete GNOME plain/LUKS and detached cold/warm boot proof.

Record the actual commits and bundle hashes for embedded frontends, not a guessed shared pin.
Arm64/v2, Tuna installer admission, overlays, and hardware need separate qualification and budget decisions.
Coordinate with the existing installer map and integrity work. This candidate does not refactor those maps.

Before periodic execution, review source and tests, then approve and run the single diagnostic.
Inspect its artifacts and failures. Rebase onto current config and agree the budget.
Remove duplicate equivalent schedules only after review. Then explicitly authorize activation.
