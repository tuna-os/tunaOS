# Q4 2026 Adoption-Momentum Plan

**Milestone**: Q4 2026 "Mature" (closes 2026-12-30)
**Tracker**: #1743 | **Prepared**: 2026-08-15 | **Last refreshed**: 2026-08-24 | **Owner**: strategist (leads; levers owned per row)
**Precondition**: Q3 checkpoint 2026-08-22 (#1299) — descope decisions for Bonito (#272) / Redfin (#1123) attach here with named owners and first-PR dates. **Status 08-24: checkpoint date elapsed; decision record still 6/6 blank (T-9 refresh PR #1998 ready); precondition UNMET until sign-off.**

## Why this plan exists

Q3 proved milestones without dated, sequenced execution drift: 4 strategic goals sat open with zero movement until a forced checkpoint. Q4 inherits that risk at larger scale while the org's best-ever adoption signals land **now**:

- First external human contributions merged 2026-08-14 — docs #234 (dchaudhari7177), docs #239 (Elonon901001); bootc-migrate daegalus 08-05. GFI → merged-PR conversion loop proven end-to-end (#1537, #1714).
- DistroWatch exposure drafted with referral metric wired (#1491).
- tunaos 55 stars (+14.6% in 9 days, 48→55, 08-01→08-10).

Without sequencing, Hacktoberfest momentum dissipates into Q4 backlog noise and the "Mature" claim (#1348, ADOPTERS.md empty) stays unfalsifiable.

## Dated milestones

| Date | Milestone | Owner | Evidence |
|------|-----------|-------|----------|
| **09-15** | Hacktoberfest seeding complete — 15–20 usable GFI across ≥6 repos | strategist + guide | HACKTOBERFEST tracker (#1537); zero-GFI repos (gtk-office-suite, tunaos-packages, wootc) closed |
| 09-22 | Q3 checkpoint decisions integrated into Q4 rows — every descope has owner + first-PR date | strategist | Q4-ADOPTION-PLAN updated; #1299 close-out |
| **10-01** | Hacktoberfest launch — curated GFI live, welcome docs linked, conversion target: ≥10 merged PRs from new contributors | outreach + strategist | GitHub Events / PR census |
| 10-15 | Mid-Hacktoberfest check — conversion rate vs target; re-seed weak repos | outreach | tracker refresh |
| 10-31 | Hacktoberfest close — total merged PRs, unique contributors, retention follow-up (thank-you + next-step issues) | outreach | post-event report |
| **11-01** | ADOPTERS.md first production entries (#1348) + adoption-metrics monthly snapshot (#1174) | strategist | ADOPTERS.md, ADOPTION-METRICS.md snapshot |
| 11-15 | Q4 mid-quarter health check — goal-by-goal status vs Q4-MATURE-DEFINITION.md | strategist | Q4 checkpoint sheet |

## Lever owners

| Lever | Tracker | Owner |
|-------|---------|-------|
| Hacktoberfest seeding + conversion | #1537 | strategist / guide |
| DistroWatch exposure + referral metric | #1491 | outreach |
| ADOPTERS.md production entries | #1348 | strategist |
| Adoption metrics monthly snapshot | #1174 | strategist |
| Community governance model | #1168 | strategist |
| Issue triage policy (queue actionability) | #1195 | strategist |

## Risk: Q4 opening blockers inherited from Q3

- **App `workflows` permission (#1557, #1991)** — uncollected maintainer decision; blocks CI-fix PRs, which are the largest GFI surface for Hacktoberfest core-code conversions. Still open as of 08-24 (#1991 reopened the gap).
- **Release parity (#1254)** — gnome-only daily; non-gnome flavors stale 40d. Fix #1588 still merge-eligible 10+ days (queue-bound, not design-bound). Blocks "all flavors downloadable" claim that new visitors test first.
- **NVIDIA family (#1383/#1499)** — initramfs regression **closed 08-14** (#1499, fixes #1503/#1523 merged), but 6 editions still zero assets since 07-05 (staff test: nightly green + gnome-nvidia assets by 09-01). Blocks flavor-equality mandate (#1316) and NVIDIA-focused outreach.

---
*Planning artifact by strategist agent (ACMM L6 — full mode). Status: DRAFT — dates firm at 08-22 checkpoint; refreshed 08-24 with risk updates. Decision record sign-off (#1998/#1299) is the gating input.*
