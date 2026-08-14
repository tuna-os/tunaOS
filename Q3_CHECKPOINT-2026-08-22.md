# Q3 2026 Checkpoint — Decision Sheet (2026-08-22)

**Milestone**: Q3 2026 "Expand Coverage" (closes 2026-09-30)
**Tracker**: #1299 | **Prepared**: 2026-08-11 | **Last refreshed**: 2026-08-14 (T-8) | **Decision authority**: maintainer

> **Correction (2026-08-13, #1317)**: every "shimonenator" reference below assumed a
> human external contributor. The maintainer confirmed the account is a Google
> Antigravity agent, misattributed by GitHub — `commit.author.name` is
> `antigravity` on every one of that account's commits.
>
> **Point-refresh (2026-08-14, T-8)**: the "no external contributor" framing
> above is now **superseded**. Two external human PRs merged in docs the same
> day — #234 (QEMU/KVM evaluation guide, 177 lines, by Dipak Chaudhari) and
> #239 (gurnard pantheon edition listing fix, by Shawn). This is the first
> verifiable external human capacity signal and proves the GFI onboarding loop
> converts (seed → PR → merge). It does **not** change the #272/#1123 staff-test
> math — 2 docs PRs in one day is not build-tooling capacity — but "external
> capacity: none" is no longer accurate, and bus-factor framing (#1095) and the
> Hacktoberfest pool estimate (#1537) both improve.

## T-8 refresh (2026-08-14) — what changed since T-10

| Input | T-10 (08-12) | T-8 (08-14) | Source |
|-------|--------------|-------------|--------|
| ADR coverage (#1094) staff test | 2 ADR PRs open | ✅ **Met** — ADR 0003 (#1369) + ADR 0004 (#1370) merged 08-13 | PR states |
| RFC disposition (#1363) | 11 branches undetermined | 11 RFC branches still undetermined; 97 total branches on tunaos; disposition pass due **at** this checkpoint | branch list |
| GFI pool (#1362) | ZERO usable | **~6 usable seeds** — tunaos #1496/#1351, docs #204/#158/#157, protota #193 (verified 08-14); **+2 converted 08-14** (docs #234/#239 by external humans) → net usable pool ≈ 8 | label search |
| External capacity | shimonenator (agent, misattributed) | **2 external humans merged docs PRs 08-14** (#234 QEMU/KVM guide — 177 lines; #239 gurnard listing fix) — first verifiable human capacity; not yet build-tooling capacity | #1317 superseded 08-14, ROADMAP |
| Release parity (#1254) | gnome daily to 08-11; others 30–37d stale | gnome daily through **08-14** (`gnome-20260814`); kde/xfce/niri/cosmic/gnome50 stale 40d (since 07-05), gnome-nvidia 33d (since 07-12) — scheduled pipeline still gnome-only | Releases API |
| NVIDIA (#1383) | overlay builds regressed 08-12 | **Worse** — initramfs regression #1499 (5 variants, 10/10 nightlies red); fixes #1503/#1523 in flight | #1499 |
| Q4 milestone fidelity (#1307) | 7/9 trackers unattached | ✅ **Fixed** — all trackers attached (verified 08-13); milestone #3 = 10 open / 1 closed | #1307, milestone |
| Docs adoption surface | 3 P0s open | ✅ **Recovered** — #103 pagination, #115 flatpak deploy, #135 404 links all closed 08-13 | docs issues |
| wootc planning (#1358) | no ROADMAP/LICENSE | ROADMAP (wootc#116) + LICENSE-GPL-2.0/LICENSE-MIT landed; **CONTRIBUTING still missing** | wootc tree |

## Purpose

Make Q3 carryover an explicit decision, not a discovery. For every open Q3 goal, choose one of:

| Decision | Meaning | Consequence |
|----------|---------|-------------|
| **STAFF** | Named owner + concrete first PR by 2026-09-01 | Goal stays in Q3 |
| **DESCOPE → Q4** | Explicitly moved to Q4 milestone with named owner | Q3 closes clean; Q4 load acknowledged |
| **DROP** | Goal no longer pursued; close issue | Removes noise; revisit at Q5 planning |

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

- **Release reliability is the top new risk since T-10**: 08-13 nightly failed across the variant matrix (Yellowfin, Bonito…); NVIDIA initramfs regression #1499 has 5 variants on 10/10 red nightlies (fixes #1503/#1523 in flight); Asahi manifest gate red nightly (#1411); live-overlay artifacts red for guppy/grouper/bonito-rawhide (#1397). Every one of these blocks the flavor-equality mandate (#1316) and the parity decision above.
- **GFI pool improved but below target**: ~6 usable seeds verified 08-14 (tunaos #1496/#1351, docs #204/#158/#157, protota #193) vs ZERO at 08-12 — and the loop **converts**: docs #234 (QEMU/KVM guide) and #239 both merged 08-14 from external humans. Net usable pool ≈ 8 vs the 15–20 needed by the 09-15 seeding deadline for Hacktoberfest (10-01) (#1362, #1347). CONTRIBUTING's good-first-issue link fixed; the meta-tracker #1308 itself carries the label and is not a task.
- **External capacity emerging but not yet build-tooling capacity**: post-retraction (#1317) the only human was hanthor; on 08-14 two external humans merged docs PRs (#234/#239). #272 and #1123 staff tests still have no borrowed build-tooling capacity path; **DESCOPE remains the realistic outcome for both unless concrete PRs land by 08-22**.
- **Q4 dependency risk**: Q4 milestone #3 = 10 open / 1 closed; trackers now attached (fidelity fixed, #1307). Bonito GA and Redfin GA already appear as Q4 rows — every Q3 descope adds Q4 load before Q4 starts. Q4 also carries adoption metrics snapshot (#1174, first 11-01), governance (#1168), branch protection (#1167), Fedora 45 planning (#1171).
- **Release parity**: GNOME daily through 08-13 (gnome-20260813). kde/xfce/niri/cosmic/gnome50 stale **40 days** (since 07-05); gnome-nvidia stale 33 days (since 07-12). Browser-catalog parity gate (#1322) fixed the on-demand path; scheduled GitHub Releases pipeline remains GNOME-only.
- **Planning debt (mid-cycle)**: wootc ROADMAP + LICENSE landed but CONTRIBUTING missing (#1358); gtk-office-suite planning gap open (#1359); tromso stable release untracked — zero releases, zero milestones (#1371).
- **Enterprise posture**: ADOPTERS.md empty vs Q4 "Mature" claim (#1348); Redfin alpha dropped from Q3 (#1123); branch protection unverified (#1167).
- **Docs adoption surface recovered**: all three docs P0s closed 08-13 (#103 pagination, #115 flatpak deploy, #135 404 links) — next step is Cloudflare Web Analytics instrumentation per ADOPTION-METRICS.md (#1174).

## Strategist recommendation (input — decision authority stays with maintainer)

| Goal | Recommended | Rationale |
|------|-------------|-----------|
| #272 Bonito GA | **DESCOPE → Q4** unless #1256 exits draft by 08-22 | Zero movement since 07-19; T2 profile still draft; Fedora 44 superseded by Fedora 45 planning (#1171); external capacity emerging (docs 08-14) but not build-tooling capacity |
| #1123 Redfin alpha | **DESCOPE → Q4** with named owner | Enterprise flagship, but external capacity is docs-only so far (08-14) and no package-gap PRs have landed; descope explicitly rather than silently |
| #1093 RFC governance | **STAFF (close-out)** | Policy merged (#1352); finish the 11-branch disposition pass **at** this checkpoint (#1363); then close the goal |
| #1094 ADR coverage | ✅ **Met — close out** | ADR 0003 + ADR 0004 merged 08-13; mark completed at checkpoint |
| #1316 Flavor equality | **STAFF cadence parity** | Catalog parity done (#1322); scheduled Releases parity (#1254) is the remaining deliverable — but blocked by #1499 NVIDIA + nightly matrix failures |
| #1323 Package sourcing | **STAFF** | Draft exists (#1330); merge + allowlist by 08-22 keeps the audit on schedule |

## Decision calendar

| Date | Event | Owner |
|------|-------|-------|
| 2026-08-22 | **Checkpoint decision sheet filled** (table below) | maintainer (strategist prepares) |
| 2026-08-24 | shimonenator 14-day window closes (moot — retracted) | — |
| 2026-09-01 | Staff-test deadline: first PR for any STAFF goal | goal owners |
| 2026-09-15 | Hacktoberfest GFI seeding deadline (15–20 seeds) | outreach + strategist (#1362/#1347) |
| 2026-09-30 | Q3 milestone closes | all |
| 2026-10-01 | Hacktoberfest 2026 opens | all |

## Decision record (fill at 2026-08-22)

| Goal | Decision (STAFF/DESCOPE/DROP) | Owner | First PR / descope ref | Date |
|------|-------------------------------|-------|------------------------|------|
| #272 Bonito GA | ⬜ | | | |
| #1123 Redfin alpha | ⬜ | | | |
| #1093 RFC governance | ⬜ | | | |
| #1094 ADR coverage | ⬜ | | | |
| #1316 Flavor equality | ⬜ | | | |
| #1323 Package sourcing | ⬜ | | | |

## Outcome recording

After the checkpoint, update the ROADMAP.md Q3 status table (per #1299 step 3) so carryover is a decision, not a discovery.

---
*Prepared by strategist agent (ACMM L6 — full mode). Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*
