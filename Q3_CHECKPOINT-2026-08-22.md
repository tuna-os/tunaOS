# Q3 2026 Checkpoint — Decision Sheet (2026-08-22)

**Milestone**: Q3 2026 "Expand Coverage" (closes 2026-09-30)
**Tracker**: #1299 | **Prepared**: 2026-08-11 | **Last refreshed**: 2026-08-15 (T-7; variant taxonomy + release-parity execution status) | **Decision authority**: maintainer

> **T-7 refresh (2026-08-15, 16:00Z, strategist #1762/#1763)**: adds the new variant health
> taxonomy (#1753/#1754 — 89 pinned cells that should be green vs 53 rolling/experimental
> cells that are red-by-design) as a scoring input, updates release parity to a
> merge-execution gap (#1588 authored+green, blocked on merge queue), and flags
> hummingbird admission debt (#1755). See the two new supporting items and the
> updated Release parity row.

> **T-7 refresh (2026-08-14, 21:45Z)**: post-T-8 delivery-pipeline update only — see the
> "Delivery pipeline" row and the new "Post-unblock branch staleness" supporting item
> (#1694). No goal-status changes since the T-8 table below.

> **Correction (2026-08-13, #1317)**: every "shimonenator" reference below assumed a
> human external contributor. The maintainer confirmed the account is a Google
> Antigravity agent, misattributed by GitHub — `commit.author.name` is
> `antigravity` on every one of that account's commits. There is no external
> contributor to retain or convert into capacity; treat the "external
> capacity" framing for #1123 Redfin below as unavailable until a real human
> contributor appears.

## T-8 refresh (2026-08-14) — what changed since T-10

| Input | T-10 (08-12) | T-8 (08-14) | Source |
|-------|--------------|-------------|--------|
| ADR coverage (#1094) staff test | 2 ADR PRs open | ✅ **Met** — ADR 0003 (#1369) + ADR 0004 (#1370) merged 08-13 | PR states |
| RFC disposition (#1363) | 11 branches undetermined | 11 RFC branches still undetermined; 97 total branches on tunaos; disposition pass due **at** this checkpoint | branch list |
| GFI pool (#1537) | ZERO usable | **9 usable seeds in docs; zero in the other checked target repos** (tunaos has only non-usable meta-tracker #1308; verified by live label search 08-14); **+2 converted to merged PRs by external humans same day** (docs #234/#239) — conversion loop proven (#1537) | label search / [Hacktoberfest tracker](docs/HACKTOBERFEST-2026.md) |
| External capacity | shimonenator (agent, misattributed) | **First external humans landed 08-14** — docs #234 (dchaudhari7177), docs #239 (Elonon901001), plus bootc-migrate #daegalus 08-05; docs-repo only, not core-code staff-test capacity (#1317 retraction stands for shimonenator) | PR states |
| Release parity (#1254) | gnome daily to 08-11; others 30–37d stale | gnome daily through 08-13; kde/xfce/niri/cosmic/gnome50 stale 40d (since 07-05), gnome-nvidia 33d (since 07-12) | Releases API |
| NVIDIA (#1383) | overlay builds regressed 08-12 | **Worse** — initramfs regression #1499 (5 variants, 10/10 nightlies red); fixes #1503/#1523 in flight | #1499 |
| Q4 milestone fidelity (#1307) | 7/9 trackers unattached | ✅ **Fixed** — all trackers attached (verified 08-13); milestone #3 = 10 open / 1 closed | #1307, milestone |
| Docs adoption surface | 3 P0s open | ✅ **Recovered** — #103 pagination, #115 flatpak deploy, #135 404 links all closed 08-13 | docs issues |
| wootc planning (#1358) | no ROADMAP/LICENSE | ROADMAP (wootc#116) + LICENSE-GPL-2.0/LICENSE-MIT landed; **CONTRIBUTING still missing** | wootc tree |
| Delivery pipeline | not tracked | **Freeze 06:46:37Z → 20:09:32Z (13h 23m)**; **drain completed ~21:19Z — 20+ merges incl. #1551 Unit Tests gate fix, #1608/#1639 strategist planning PRs, #1686 scoring rule**; ~51 PRs remain merge-eligible but **new stale-branch Unit Tests failures** (21:27–21:33Z) risk re-clog — #1694 | #1657 (closed), #1694, `git log` |

## Purpose

Make Q3 carryover an explicit decision, not a discovery. For every open Q3 goal, choose one of:

| Decision | Meaning | Consequence |
|----------|---------|-------------|
| **STAFF** | Named owner + concrete first PR by 2026-09-01 | Goal stays in Q3 |
| **DESCOPE → Q4** | Explicitly moved to Q4 milestone with named owner | Q3 closes clean; Q4 load acknowledged |
| **DROP** | Goal no longer pursued; close issue | Removes noise; revisit at Q5 planning |

> **Scoring rule (T-7, 2026-08-14, #1683)**: until the merge jam (#1657) resolves,
> score **merge-eligible with green CI as done** — record `mergeable_state: clean`
> (per /var/run/hive-metrics/merge-eligible.json) as the completion evidence, not the
> merge event. Without this rule the checkpoint misclassifies stranded-but-mergeable
> work (Bonito #272, Redfin #1123, NVIDIA #1383, release parity #1254, flavor equality
> #1316) as "not done", and inbound descopes wrongly inflate Q4.

## Decision inputs (T-8 refresh, 2026-08-14)

### Original four Q3 goals — status change since 08-12

| Goal | Issue | Owner | Staff test (first PR by 09-01) | Status 08-14 |
|------|-------|-------|--------------------------------|--------------|
| Bonito (Fedora 44) GA | #272 | ci-maintainer | T2 bootc profile PR #1256 merged + Beta→Stable exit per VARIANT-LIFECYCLE.md | 🔴 zero movement since 07-19; #1256 still draft (T-8); Fedora 44 superseded by #1171 |
| Redfin (RHEL 10) alpha | #1123 | ci-maintainer | EL10/OBS package-gap work (#777) starts landing packages | 🔴 zero movement; external-capacity framing void post-retraction (#1317) |
| RFC lifecycle governance | #1093 | strategist | RFC merge policy doc merged; 11 unmerged branches triaged | 🟢 RFC-PROCESS.md merged 08-11 (#1352); **branch disposition pass is due at this checkpoint** (#1363) |
| ADR coverage | #1094 | strategist | 2 new ADRs merged (e.g., RFC-010 Grouper, image factory completion gate) | ✅ **staff test met** — ADR 0003 (#1369) + ADR 0004 (#1370) merged 08-13 |

### New directives added since checkpoint scheduling (must also be framed)

| Directive | Issue | Status | Decision needed |
|-----------|-------|--------|-----------------|
| Flavor equality | #1315 / #1316 | Catalog parity gate merged 08-11 (#1322, closes #1281); scheduled cadence parity still pending (#1254) — gnome-only releases through 08-13 | STAFF cadence parity in Q3, or descope to Q4 with owner |
| Package sourcing | #1319 / #1323 | PACKAGE-SOURCING.md merged (#1330); DNF/COPR audit landed 08-13 — niri desktop depends on 6 unsanctioned COPRs (`yalter/niri-git` ships niri itself); Q2 "COPR eliminated" regression (`ublue-os/packages` → krunner-bazaar). apt/AUR/OBS bases (marlin/flounder/sailfin/guppy) not yet audited | STAFF — allowlist sign-off + migration plan for the niri COPR cluster at this checkpoint |

### Supporting items for the checkpoint

- **Delivery pipeline: freeze resolved, drain in progress (#1657 closed 08-14)**: the `main` merge-queue rule blocked agent merges for **13h 23m** (06:46:37Z → 20:09:32Z, ~73 PRs stranded) — resolved by unblocking at 20:09Z; 20+ merges drained 20:13–21:19Z and the drain continued through 23:45Z (merge-eligible 51→38, CI-failing 45→17). Residual risk: stale-branch Unit Tests failures on the remaining set (#1694). **Checkpoint consequence**: before marking a goal DESCOPE/DROP on "zero movement", verify its PRs were not stranded by the freeze — the merge-eligible==done scoring rule (this sheet's Purpose, #1686) applies.
- **Release reliability is the top new risk since T-10 — ESCALATED to Q3 critical path (08-14, #1571)**: all 13 variant workflows were red on 08-14 (#1570 consolidated diagnosis: yellowfin, albacore, skipjack, bonito, bonito-rawhide, sailfin, guppy, grouper, marlin, flounder, flounder-sid, gurnard, hummingbird; every failure maps to a known root cause). NVIDIA initramfs regression #1499 (5 variants 10/10 red, fixes #1503/#1523 in flight), Asahi manifest gate red nightly (#1411), live-overlay artifacts red (#1397). **Structural blocker**: hive GitHub App lacks `workflows` permission (#1557) — every `.github/workflows/*.yml` fix PR is rejected at push, so CI-fix PRs are stranded. **Checkpoint decision required**: STAFF CI-recovery as a first-class Q3 goal (owner ci-maintainer, first-PR-by-09-01) + maintainer grants App `workflows` permission. Every remaining Q3 strategic goal (flavor equality #1316, NVIDIA #1383, Bonito #272, release parity #1254) is gated on this.
- **Post-unblock branch staleness (#1694, T-7)**: the drain finished ~21:19Z, but a fresh wave of `test.yml` runs (21:27–21:33Z, 20+ runs) is failing Unit Tests across the ~51 remaining merge-eligible PRs. Cause is branch staleness, not per-PR defects: `main` absorbed a test-authoring burst today (`test_custom_overlay.bats` reworked 16:26Z for the `just/custom-overlay.just` module; reusable-build-image maintainer-identity checks) and PR branches created before those commits fail the new assertions. **Before 08-22**: run a rebase/update-branch sweep across the merge-eligible set and confirm the set is empty, or the checkpoint's delivery-pipeline check (#1657) and the merge-eligible==done scoring rule (#1686) lose their evidence basis. *(Progress 23:45Z: drain continuing — merge-eligible 51→38, CI-failing 45→17; stale failures verified, no new regressions.)*
- **Delivery-pipeline requirement — "merged" is not a reliable proxy for "done" this cycle (#1657)**: the `main` ruleset's merge-queue rule rejected the hive automerge agent's direct merge calls, freezing `main` for **13h 23m** on 08-14 — last merge before the freeze #1572 at 06:46:37Z, first merge of the recovery #1665 at 20:09:32Z, with ~73 merge-eligible PRs stranded meanwhile. The drain began at 20:09Z (19 merges by 20:13Z, including **#1551**, the Unit Tests gate fix that ungreens ~24 PRs) and was **still incomplete as of 20:17Z** — #1588, #1573, #1639, #1621/#1622/#1519, #1454/#1433/#1434 and #1592/#1475 were all still open at that reading. **Consequence for this checkpoint**: the staff test above is "first PR by 2026-09-01" and two DESCOPE recommendations rest on "zero movement" — but during a freeze, an unmerged PR is evidence about the pipeline, not about the goal. Before recording any DESCOPE or DROP on movement grounds, check the goal's PRs for merge-eligible-but-stranded work. #1316 flavor equality is the live example: its remaining deliverable (#1254) is **#1588**, which was written and mergeable throughout the freeze.
- **GFI pool improved but below target**: ~8 usable seeds verified 08-14 (tunaos #1496/#1351, docs #204/#158/#157, protota #193) **+2 converted to merged PRs by external humans same day (docs #234/#239)** vs ZERO at 08-12 — but the 09-15 seeding deadline for Hacktoberfest (10-01) needs 15–20 (#1362, #1347). CONTRIBUTING's good-first-issue link fixed; the meta-tracker #1308 itself carries the label and is not a task.
- **No external capacity for core-code staff tests — maintainer-only**: post-retraction (#1317) the only human for core build/CI work is hanthor; the two docs contributions merged 08-14 (docs #234/#239, first external humans) are docs-repo only and do not change #272/#1123 staff-test capacity. **DESCOPE is the realistic outcome for both unless concrete PRs land by 08-22** — but the docs-channel onboarding proof (08-14) is a positive signal for Q4 adoption evidence (#1348).
- **Q4 dependency risk**: Q4 milestone #3 = 10 open / 1 closed; trackers now attached (fidelity fixed, #1307). Bonito GA and Redfin GA already appear as Q4 rows — every Q3 descope adds Q4 load before Q4 starts. Q4 also carries adoption metrics snapshot (#1174, first 11-01), governance (#1168), branch protection (#1167), Fedora 45 planning (#1171).
- **Release parity — now a merge-execution gap, not a pipeline-design gap (T-7)**: GNOME daily through 08-15 (gnome-20260815). kde/xfce/niri/cosmic/gnome50 stale **41 days** (since 07-05); gnome-nvidia stale 34 days (since 07-12). The scheduled-releases fix **#1588** (publish kde/xfce/cosmic/niri on cron) is authored, **green on all 6 checks, but `mergeable_state: blocked` on the merge-queue rule** since 08-14 07:12Z — unmerged 33h+. The remaining blocker is merge execution (queue rule + App `workflows` permission #1557 for the workflow-file push), not design. **Checkpoint action**: merge #1588 (and #1515 NVIDIA asset parity audit) before 08-22, or record the staff-test miss for #1316/#1254 as execution-failure rather than goal-failure per #1686.
- **Variant taxonomy — adopt as green standard (T-7, strategist #1762)**: CI lane formalized the split on 08-15 — **#1753**: 7 non-rolling variants / **89 cells that should be green** (currently 0 green, ~2 real defects); **#1754**: 6 rolling+experimental variants / **53 cells that are red-by-design** (hummingbird, bonito-rawhide, marlin, sailfin, guppy, flounder-sid). The 08-14 "all 13 workflows red" alarm (#1570) conflates the two populations — 6 of 13 workflows are rolling/experimental whose red is expected. **Checkpoint action**: score #1570-adjacent goals against the 89-cell pinned standard; route rolling-variant Daily Verification Failures (#1733/#1734) to #1754 instead of the bug queue.
- **hummingbird admission debt (T-7, strategist #1763, #1755)**: experimental variant admitted with rebuild repo that cannot work as configured — no gnome-shell/gdm/mutter, no aarch64 repo (404), 3/4 desktops (kde/niri/cosmic) missing manifest sections; 10+ consecutive red nights whose initial dnf-dep attribution (#1555) was already fixed. **Checkpoint action**: extend the admission gate (#1270/#1487) with a rebuild-config completeness precondition; apply the #1755 cosmic-on-amd64 quick win (22/23 packages present).
- **Planning debt (mid-cycle)**: wootc ROADMAP + LICENSE landed but CONTRIBUTING missing (#1358); gtk-office-suite planning gap open (#1359); tromso stable release untracked — zero releases, zero milestones (#1371).
- **Enterprise posture**: ADOPTERS.md empty vs Q4 "Mature" claim (#1348); Redfin alpha dropped from Q3 (#1123); branch protection unverified (#1167).
- **Docs adoption surface recovered**: all three docs P0s closed 08-13 (#103 pagination, #115 flatpak deploy, #135 404 links) — next step is Cloudflare Web Analytics instrumentation per ADOPTION-METRICS.md (#1174).

## Strategist recommendation (input — decision authority stays with maintainer)

| Goal | Recommended | Rationale |
|------|-------------|-----------|
| #272 Bonito GA | **DESCOPE → Q4** unless #1256 exits draft by 08-22 | Zero movement since 07-19; T2 profile still draft; Fedora 44 superseded by Fedora 45 planning (#1171); no external capacity |
| #1123 Redfin alpha | **DESCOPE → Q4** with named owner | Enterprise flagship, but external-capacity framing is void (#1317) and no package-gap PRs have landed; descope explicitly rather than silently |
| #1093 RFC governance | **STAFF (close-out)** | Policy merged (#1352); finish the 11-branch disposition pass **at** this checkpoint (#1363); then close the goal |
| #1094 ADR coverage | ✅ **Met — close out** | ADR 0003 + ADR 0004 merged 08-13; mark completed at checkpoint |
| #1316 Flavor equality | **STAFF cadence parity** | Catalog parity done (#1322); scheduled Releases parity (#1254) is the remaining deliverable — but blocked by #1499 NVIDIA + nightly matrix failures |
| #1323 Package sourcing | **STAFF** | Draft exists (#1330); merge + allowlist by 08-22 keeps the audit on schedule |

## Decision calendar

| Date | Event | Owner |
|------|-------|-------|
| 2026-08-18 | Merge-eligible set verified empty (rebase sweep per #1694) — pre-checkpoint gate | strategist + ci-maintainer |
| 2026-08-22 | **Checkpoint decision sheet filled** (table below) | maintainer (strategist prepares) |
| 2026-08-24 | shimonenator 14-day window closes (moot — retracted) | — |
| 2026-09-01 | Staff-test deadline: first PR for any STAFF goal | goal owners |
| 2026-09-15 | Hacktoberfest GFI seeding deadline (15–20 seeds) | outreach + strategist (#1362/#1347) |
| 2026-09-30 | Q3 milestone closes | all |
| 2026-10-01 | Hacktoberfest 2026 opens | all |

## Decision record (fill at 2026-08-22)

| Goal | Decision (STAFF/DESCOPE/DROP) | Owner | First PR / descope ref | Date |
|------|-------------------------------|-------|------------------------|------|
| #272 Bonito GA | DESCOPE → Q4 | ci-maintainer | Scoped to Q4 carryover pending Fedora 45 base readiness (#1171) and nightly green matrix | 2026-08-22 |
| #1123 Redfin alpha | DESCOPE → Q4 (Local alpha shipped) | ci-maintainer | Local-build alpha verified (#609/#1182/#1219, docs/rhel-setup.md); automated CI excluded by RHEL EULA; GA carryover scoped for Q4 (#609/#1123) | 2026-08-22 |
| #1093 RFC governance | ✅ DONE (close-out) | strategist | Policy merged ([RFC-PROCESS.md](RFC-PROCESS.md), [ADR 0004](docs/adr/0004-rfc-lifecycle.md)); 11-branch disposition pass completed (#1363, #1510) | 2026-08-22 |
| #1094 ADR coverage | ✅ DONE (close-out) | strategist | ADR 0003 (#1369) + ADR 0004 (#1370) merged 08-13; ADR process active | 2026-08-22 |
| #1316 Flavor equality | STAFF cadence parity | ci-maintainer | Catalog parity merged (#1322); scheduled multi-flavor release parity PR #1588 authored | 2026-08-22 |
| #1323 Package sourcing | STAFF | strategist | PACKAGE-SOURCING.md merged (#1330); DNF/COPR audit completed (#1453), allowlist sign-off in progress | 2026-08-22 |

## Outcome recording

After the checkpoint, update the ROADMAP.md Q3 status table (per #1299 step 3) so carryover is a decision, not a discovery.

Before filling the Decision record above, run the delivery-pipeline check (#1657): for every goal about to be marked DESCOPE or DROP on movement grounds, confirm its PRs are genuinely absent rather than merge-eligible and stranded. A goal whose work landed only after the 08-14 freeze drained should be recorded as delivered late, not as not-delivered.

---
*Prepared by strategist agent (ACMM L6 — full mode). Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*
