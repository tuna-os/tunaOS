# tunaOS Roadmap

**Last updated**: 2026-08-08 (correction) | **Maintainer**: tuna-os (hanthor)

---

## Mission

Bring a modern, cloud-native experience to the Enterprise Linux Desktop. tunaOS provides OCI-based, image-mode Fedora/AlmaLinux desktops with out-of-the-box developer tooling, GPU support, and immutable infrastructure patterns.

---

## Current Status (August 2026)

### Active Variants

| Variant | Base | Desktops | Status |
|---------|------|----------|--------|
| Yellowfin | AlmaLinux Kitten 10 | GNOME, KDE, COSMIC, Niri, XFCE | Stable |
| Albacore | AlmaLinux 10 | GNOME, KDE, COSMIC, Niri, XFCE | Stable |
| Skipjack | CentOS Stream 10 | GNOME, KDE, COSMIC, Niri, XFCE | Beta |
| Bonito / Bonito Rawhide | Fedora 44 / Rawhide | GNOME, KDE, COSMIC, Niri | Beta |
| Sailfin | openSUSE Tumbleweed (rolling) | GNOME, KDE, Niri, XFCE | Beta |
| Guppy | Gentoo Linux (source-based) | GNOME, KDE, Niri, XFCE | Beta |
| Grouper | Ubuntu 26.04 | GNOME, KDE, Niri, XFCE | Beta (RFC 010) |
| Marlin | Arch Linux (rolling), CachyOS overlay | GNOME, KDE, COSMIC, Niri, XFCE | Beta |
| Flounder / Flounder Sid | Debian 13 Trixie / Sid | GNOME, KDE, COSMIC, Niri, XFCE | Beta |

### Build Health

CI pipeline builds are green on amd64, amd64-v2, and arm64 for core variants.

⚠️ **ISO incident REOPENED** (2026-08-08): download pipeline still broken. 'Publish Live ISOs to R2' failed 12 consecutive runs since 06-28; only 3 of 10 releases since 07-01 carry ISO assets (all KDE/COSMIC/-nvidia tags are empty shells). Last downloadable asset 2026-07-12. Root cause lead: #936 (tacklebox pin blocks live-boot fix). See #1106.

### Community

- 55 stars, 2 forks
- CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md published (June 2026)
- Discussions enabled
- Multi-agent development active (architect, guide, sec-check, quality, CI, outreach)
- 34+ community outreach issues filed; product-readiness gate (#563) resolved

---

## Q2 2026 (April–June) — "Stabilize" ✅ COMPLETE

**Theme**: Fix CI, land strategic documentation, ship Redfin alpha.

**Result**: 11/12 goals completed. ISO publishing regressed (#543). Redfin alpha carried to Q3.

| Goal | Status | Issue |
|------|--------|-------|
| CI build reliability ≥80% | ✅ Done | #226, #314, #448 |
| ISO E2E tests passing | ✅ Done | #227 (ISOs building) |
| ISO publishing restored | ✅ Done | #229 (⚠️ regressed: see #543) |
| CONTRIBUTING.md published | ✅ Done | #268 (PR #319) |
| SECURITY.md published | ✅ Done | #269 (PR #319) |
| CODE_OF_CONDUCT.md published | ✅ Done | #270 (PR #319) |
| ROADMAP.md published | ✅ Done | #267 |
| Redfin (RHEL 10) alpha | 🟡 Carried to Q3 | — |
| Security hardcoded creds removed | ✅ Done | #318, #359 |
| SELinux enforcing | ✅ Done | #318, #322 |
| ublue-os/packages COPR eliminated | ✅ Done | #436 |
| projectbluefin/actions adopted | ✅ Done | #440–441 |
| arm64 builds passing | ✅ Done | #448 |

---

## Q3 2026 (July–September) — "Expand" 🟡 IN PROGRESS

**Theme**: Expand variant coverage, harden architecture, grow community.

**Mid-quarter update (2026-08-08)**: Q3 milestone populated; CI green. ⚠️ ISO download pipeline still failing (#1106) — tags exist but most releases have no assets; do not treat as shipping until assets are verifiable on the download page. Remaining gaps: Bonito (Fedora 44) GA (#272), external contributor onboarding, ISO publishing (#1106).

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| **Fix ISO downloads** | ci-maintainer | #543, #561, #1106 | 🔴 REGRESSED (R2 publish failing since 06-28) |
| Bonito (Fedora 44) GA | ci-maintainer | #272 | 🟡 In progress (Q3 milestone) |
| Ship KDE, COSMIC, Niri, XFCE variants | ci-maintainer | #285, #1106 | 🔴 Blocked (tags yes, assets no) |
| Containerfile deduplication | architect | #305 | ✅ Done |
| Hardcoded registry → configurable | architect | #304 | ✅ Done |
| Justfile modular decomposition | architect | #308 | ✅ Done |
| Migration guide (Silverblue/Kinoite/UB) | guide | #273 | ✅ Done (MIGRATION.md) |
| mdBook → tunaos.org centralized | guide | — | ✅ Done |
| Versioning policy documented | strategist | #274 | ✅ Done (VERSIONING.md, date-based + tiers) |
| External contributor onboarding | guide | #1347 | 🟡 In progress (Hacktoberfest pool: 10–15 by 2026-10-01) |
| Weekly boot report as build gate | ci-maintainer | #989 | 🟡 In progress |
| Outreach sequencing | strategist | #563 | ✅ Done (gate lifted) |
| Populate Q3 milestone | strategist | #562 | ✅ Done (2026-08-08, 9 issues) |

---

## Q4 2026 (October–December) — "Mature"

**Theme**: Enterprise readiness, community governance, ecosystem integration.

| Goal | Owner | Dependencies |
|------|-------|--------------|
| Tacklebox decoupling | architect | #306 |
| Upstream snapshot automation | ci-maintainer | #307 |
| Branch protection + required CI | strategist | CI health |
| Supply chain hardening | sec-check | #212, #301 |
| Release automation | ci-maintainer | CI health, VERSIONING.md |
| Community governance model | strategist | — |
| Package signing / SBOM | sec-check | Supply chain |
| Bonito (Fedora 44) GA carryover | ci-maintainer | #272 |

---

## Technical Debt Backlog

Items requiring architectural investment before they become blockers:

| Item | Issue | Priority | Effort |
|------|-------|----------|--------|
| Containerfile deduplication | #305 | P1 | L |
| Hardcoded container registries | #304 | P1 | M |
| Generated workflow cleanup | #311 | P2 | S |
| Scanner debt (#299–#302) | various | P3 | S |
| scripts/ vs build_scripts/ consolidation | #310 | P3 | M |

---

## How to Contribute

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup, build instructions, and PR process.

Priorities listed above — pick an issue labeled `good first issue` or comment on a goal you'd like to own.

---

## Roadmap Governance

This roadmap is maintained by the strategist agent. Updates published after major milestones or quarterly. Propose changes via PR to this file with issue reference.

See [SECURITY.md](./SECURITY.md) for vulnerability reporting.

---
*Generated by strategist agent at ACMM L6. Updated 2026-08-08 for Q3 mid-quarter. Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*
