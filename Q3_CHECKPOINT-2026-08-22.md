# Q3 2026 Checkpoint — Decision Sheet (2026-08-22)

**Milestone**: Q3 2026 "Expand Coverage" (closes 2026-09-30)
**Tracker**: #1299 | **Prepared**: 2026-08-11 | **Decision authority**: maintainer

## Purpose

Make Q3 carryover an explicit decision, not a discovery. For every open Q3 goal, choose one of:

| Decision | Meaning | Consequence |
|----------|---------|-------------|
| **STAFF** | Named owner + concrete first PR by 2026-09-01 | Goal stays in Q3 |
| **DESCOPE → Q4** | Explicitly moved to Q4 milestone with named owner | Q3 closes clean; Q4 load acknowledged |
| **DROP** | Goal no longer pursued; close issue | Removes noise; revisit at Q5 planning |

## Decision inputs (as of 2026-08-11)

### Original four Q3 goals — zero movement since 08-08

| Goal | Issue | Owner | Staff test (first PR by 09-01) |
|------|-------|-------|--------------------------------|
| Bonito (Fedora 44) GA | #272 | ci-maintainer | T2 bootc profile PR #1256 merged + Beta→Stable exit per VARIANT-LIFECYCLE.md |
| Redfin (RHEL 10) alpha | #1123 | ci-maintainer | EL10/OBS package-gap work (#777, shimonenator docs) starts landing packages |
| RFC lifecycle governance | #1093 | strategist | RFC merge policy doc merged; 11 unmerged branches triaged |
| ADR coverage | #1094 | strategist | 2 new ADRs merged (e.g., RFC-010 Grouper, image factory completion gate) |

### New directives added since checkpoint scheduling (must also be framed)

| Directive | Issue | Status | Decision needed |
|-----------|-------|--------|-----------------|
| Flavor equality | #1315 / #1316 | Catalog parity gate merged 08-11 (#1322, closes #1281); scheduled cadence parity pending (#1254) | STAFF cadence parity in Q3, or descope to Q4 with owner |
| Package sourcing | #1319 / #1323 | No policy doc yet; second maintainer directive in 24h | STAFF PACKAGE-SOURCING.md draft; audit third-party repo usage |

### Supporting items for the checkpoint

- **Contributor retention**: shimonenator 14-day window closes ~08-24. Verify #1308 good-first-issue seeds landed; record whether the contributor returned (funnel proxy for ADOPTION-METRICS.md).
- **Q4 dependency risk**: Q4 is 0/9 closed; Bonito GA and Redfin GA already appear as Q4 rows — every Q3 descope adds Q4 load before Q4 starts.
- **Release parity**: non-GNOME flavors stale 37 days (#1254). The browser-catalog parity gate (#1322) fixed the on-demand path; the scheduled GitHub Releases pipeline is still GNOME-only.

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
