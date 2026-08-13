# Q3 2026 Checkpoint — Decision Sheet (2026-08-22)

**Milestone**: Q3 2026 "Expand Coverage" (closes 2026-09-30)
**Tracker**: #1299 | **Prepared**: 2026-08-11 | **Last refreshed**: 2026-08-13 (T-9) | **Decision authority**: maintainer

## Purpose

Make Q3 carryover an explicit decision, not a discovery. For every open Q3 goal, choose one of:

| Decision | Meaning | Consequence |
|----------|---------|-------------|
| **STAFF** | Named owner + concrete first PR by 2026-09-01 | Goal stays in Q3 |
| **DESCOPE → Q4** | Explicitly moved to Q4 milestone with named owner | Q3 closes clean; Q4 load acknowledged |
| **DROP** | Goal no longer pursued; close issue | Removes noise; revisit at Q5 planning |

## Decision inputs (T-10 refresh, 2026-08-12)

### Original four Q3 goals — status change since 08-11

| Goal | Issue | Owner | Staff test (first PR by 09-01) | Status 08-12 |
|------|-------|-------|--------------------------------|--------------|
| Bonito (Fedora 44) GA | #272 | ci-maintainer | T2 bootc profile PR #1256 merged + Beta→Stable exit per VARIANT-LIFECYCLE.md | 🔴 zero movement; #1256 still draft |
| Redfin (RHEL 10) alpha | #1123 | ci-maintainer | EL10/OBS package-gap work (#777, shimonenator docs) starts landing packages | 🔴 zero movement |
| RFC lifecycle governance | #1093 | strategist | RFC merge policy doc merged; 11 unmerged branches triaged | 🟢 RFC-PROCESS.md merged 08-11 (#1352); branch disposition pass due 08-22 (#1363) |
| ADR coverage | #1094 | strategist | 2 new ADRs merged (e.g., RFC-010 Grouper, image factory completion gate) | 🟢 ADR 0003 + ADR 0004 PRs open (#1369/#1370) — merge by 09-01 |

### New directives added since checkpoint scheduling (must also be framed)

| Directive | Issue | Status | Decision needed |
|-----------|-------|--------|-----------------|
| Flavor equality | #1315 / #1316 | Catalog parity gate merged 08-11 (#1322, closes #1281); scheduled cadence parity pending (#1254) | STAFF cadence parity in Q3, or descope to Q4 with owner |
| Package sourcing | #1319 / #1323 | PACKAGE-SOURCING.md drafted (PR #1330 open); third-party allowlist + per-variant audit outstanding | STAFF — merge policy doc by 08-22; audit due at checkpoint |

### Operational blockers added 2026-08-12–13 (must also be framed)

| Blocker | Issue | Evidence | Decision needed |
|---------|-------|----------|----------------|
| NVIDIA flavor family | #1383 | All six NVIDIA releases have shipped zero assets since 07-05/07-12; overlay failures remain red in the 08-13 nightly matrix (#1376/#1379/#1382) | STAFF only if nightly builds are green and `gnome-nvidia` assets are republished by 09-01; otherwise DESCOPE the all-flavors Q3 claim |
| Publish-path resilience | #1377 / #1187 | `rekor.sigstore.dev` 502s have blocked variant image builds since 08-07, including the 08-13 nightly; downstream Gate/Promote jobs cannot proceed | Carry the resilience requirement into Q4 #1187: retry/backoff plus offline attestation or an alternate transparency log |

### Supporting items for the checkpoint

- **Contributor retention → capacity**: shimonenator is ACTIVE (8 commits 08-10/11 across tunaOS + xfce-linux; last 08-11 20:26Z). 14-day window closes ~08-24 — 2 days AFTER this checkpoint. Recommend converting retention into capacity: seed GFI-scoped Bonito/Redfin packaging subtasks for the contributor **at** the checkpoint, so #272/#1123 staff tests can borrow external capacity instead of maintainer-only time.
- **GFI pool is ZERO usable (#1362)**: the #1308 seeds never landed (letters#8 is on an archived repo); CONTRIBUTING's good-first-issue link is dead. No seeds → no external capacity → the retention-window opportunity above is moot. Seed 20+ GFIs by 09-15 (#1362; outreach #1354 tracks 3→8).
- **Q4 dependency risk**: Q4 is 0/13 items closed (was 0/9); Bonito GA and Redfin GA already appear as Q4 rows — every Q3 descope adds Q4 load before Q4 starts. #1159/#1307 track Q4 goal fidelity.
- **Release parity**: GNOME releases are now daily (08-09 → 08-11, 3 assets each). kde/xfce/niri/gnome-nvidia still stale 30–37 days (#1254). Browser-catalog parity gate (#1322) fixed the on-demand path; the scheduled GitHub Releases pipeline remains GNOME-only.
- **New planning debt (mid-cycle)**: wootc ROADMAP merged (wootc#116) but CONTRIBUTING/LICENSE still missing (#1358); gtk-office-suite planning gap open (#1359); tromso stable release untracked (no releases, no milestones — core build tooling; filed as new tracker this cycle).
- **Enterprise posture**: ADOPTERS.md empty vs Q4 "Mature" claim (#1348); RHEL10/AlmaLinux topics on repo but Redfin alpha dropped (#1123); branch protection unverified (#1167).
- **Nightly reliability (08-13)**: the rekor outage is now a week-long recurring SPOF (#1377), while GHCR arm64 login failures add a second failure class. GNOME ISO daily releases remain unaffected because they use a separate path.

## Strategist recommendation (input — decision authority stays with maintainer)

| Goal | Recommended | Rationale |
|------|-------------|-----------|
| #272 Bonito GA | **DESCOPE → Q4** unless #1256 exits draft by 08-22 | Zero movement since 07-19; T2 profile in draft; Fedora 44 is now superseded by Fedora 45 planning (#1171) — carryover should be explicit, not silent |
| #1123 Redfin alpha | **STAFF with external capacity** or **DESCOPE → Q4** | Enterprise flagship; seed EL10 package-gap GFIs for shimonenator before window closes 08-24; if no seeds, descope with named owner |
| #1093 RFC governance | **STAFF** | Policy merged (#1352); finish branch disposition pass by 08-22 (#1363) |
| #1094 ADR coverage | **STAFF** | Merge ADR 0003/0004 (#1369/#1370) by 09-01; RFC backlog governance (#1093) is the long pole |
| #1316 Flavor equality | **STAFF cadence parity** | Catalog parity done (#1322); scheduled Releases parity (#1254) is the remaining deliverable |
| #1323 Package sourcing | **STAFF** | Draft exists (#1330); merge + allowlist by 08-22 keeps the 08-22 audit on schedule |

## Decision record (fill at 2026-08-22)

| Goal | Decision (STAFF/DESCOPE/DROP) | Owner | First PR / descope ref | Date |
|------|-------------------------------|-------|------------------------|------|
| #272 Bonito GA | ⬜ | | | |
| #1123 Redfin alpha | ⬜ | | | |
| #1093 RFC governance | ⬜ | | | |
| #1094 ADR coverage | ⬜ | | | |
| #1316 Flavor equality | ⬜ | | | |
| #1323 Package sourcing | ⬜ | | | |
| #1383 NVIDIA flavor family | ⬜ | | | |

## Outcome recording

After the checkpoint, update the ROADMAP.md Q3 status table (per #1299 step 3) so carryover is a decision, not a discovery.

---
*Prepared by strategist agent (ACMM L6 — full mode). Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*
