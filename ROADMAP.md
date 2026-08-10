# tunaOS Roadmap

**Last updated**: 2026-08-09 (release verified) | **Maintainer**: tuna-os (hanthor)

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

**Status terms** follow [VARIANT-LIFECYCLE.md](VARIANT-LIFECYCLE.md): `Stable`
means GA, `Beta` means published for testing on tunaos.org/download. This
table is the canonical per-variant status; tunaos.org wiki and blog copy must
track it. Notably **Bonito is Beta** (GA tracked in [#272](https://github.com/tuna-os/tunaos/issues/272)) — it is neither "Production" nor "Experimental".

### Build Health

CI pipeline builds are green on amd64, amd64-v2, and arm64 for core variants.

✅ **Downloads VERIFIED WORKING** (2026-08-08): tunaos.org/download serves 179 ISOs from R2 (newest 08-07, HTTP 200 GB-scale). ✅ **GitHub Releases RESUMED 2026-08-09**: `gnome-20260809` published 11:38 UTC with assets (incl. SBOM spdx, 52.5 MB) — first release since 07-12; the `a4b147f8` fix (build-run selection, not artifact name — see #1106) and the #1147 cadence backstop are confirmed effective. #936 (tacklebox pin) is **not** a live-boot fix hold: the `image-versions.yaml` fallback was moved to the live-boot fix (tacklebox `4fa6041`) on 07-31 by #937. What is left is a separate, narrower thing — `publish-iso-groups.yml` sets its own `TACKLEBOX_SHA: a105d6d3` (61 commits older, pre-dating the appended-overlay live path), and since `publish-isos.yml` is disabled that override is the SHA every scheduled ISO is actually built with. Those ISOs boot-gate green (run 30773566969, 08-03), so this is a divergence to close deliberately with its own boot evidence, not a hold to lift.

### Community

- 56 stars, 3 forks
- CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md published (June 2026)
- Discussions enabled
- Multi-agent development active (architect, guide, sec-check, quality, CI, outreach)
- 34+ community outreach issues filed; product-readiness gate (#563) resolved
- ⚠️ Adoption metrics untracked — no usage/telemetry data on the 179 downloadable ISOs (#1174, filed 08-08); first monthly download/usage snapshot planned for Q4
- 🟡 ROADMAP coverage improving — template merged into .github project-starter (PR #13); tunaos-packages + iso-builder seeded (08-10); still ~11/38 repos unplanned (#1295)

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

**Mid-quarter update (2026-08-10)**: Q3 milestone populated; CI green; **downloads verified working** (179 ISOs, newest 08-07). ⚠️ **Q3 at risk — checkpoint 2026-08-22** (#1299): 4 open strategic goals (#272 Bonito GA, #1123 Redfin alpha, #1093 RFC governance, #1094 ADR coverage) with zero movement since 08-08 while CI/ops work lands daily. ⚠️ **Desktop parity crisis** (#1294): tunaos-packages#133 audit shows 24/37 published editions are too small to contain their desktop (non-RPM bases: sailfin/flounder/grouper). GitHub Releases gap fixed 08-08 (#1106/#1147 closed, `a4b147f8`).

| Goal | Owner | Tracking | Status |
|------|-------|----------|--------|
| **Fix ISO downloads** | ci-maintainer | #543, #561 | ✅ Done — downloads verified working (R2, 08-07) |
| Bonito (Fedora 44) GA | ci-maintainer | #272 | 🟡 In progress (Q3 milestone) |
| Redfin (RHEL 10) alpha | ci-maintainer | #609, #1123 | 🔴 DROPPED — restored to roadmap 2026-08-08 |
| Ship KDE, COSMIC, Niri, XFCE variants | ci-maintainer | #285 | 🟡 Published but **desktop-completeness unverified** — 24/37 editions undersized per #133/#1294 |
| GitHub Releases page carries ISO assets | ci-maintainer | #1106 | ✅ Verified 08-09 — `gnome-20260809` published with assets; cadence resumed |
| Release-cadence health gate (no silent skip) | ci-maintainer | #1147 | 🟡 Root cause fixed 08-08 (`a4b147f8` fails on dropped release) — verify no silent skip 08-09 |
| Containerfile deduplication | architect | #305 | ✅ Done |
| Hardcoded registry → configurable | architect | #304 | ✅ Done |
| Justfile modular decomposition | architect | #308 | ✅ Done |
| Migration guide (Silverblue/Kinoite/UB) | guide | #273 | ✅ Done (MIGRATION.md) |
| mdBook → tunaos.org centralized | guide | — | ✅ Done |
| Versioning policy documented | strategist | #274 | ✅ Done (VERSIONING.md, date-based + tiers) |
| External contributor onboarding | guide | — | ⬜ Not started |
| Weekly boot report as build gate | ci-maintainer | #989 | 🟡 In progress |
| Outreach sequencing | strategist | #563 | ✅ Done (gate lifted) |
| Populate Q3 milestone | strategist | #562 | ✅ Done (2026-08-08, 9 issues) |
| **User-proven ISO installs roadmap** | ci-maintainer | #763 | 🟡 In progress (Phase 1 baseline dispatched #761; GUI gate #577) |
| **Apple Silicon (Asahi Linux) support** | architect / ci-maintainer | #781 | 🟡 In progress (Bonito & Grouper 36/36 verified #776; D0–D4 installer track active) |
| **Desktop parity floor (non-RPM bases)** | packaging | #133, tunaos-packages#323 | ⬜ Not started — P0 for Q4 (see #1294) |
| **Q3 checkpoint (08-22): staff or descope #272/#1123/#1093/#1094** | strategist | #1299 | ⬜ Scheduled |

---

## Q4 2026 (October–December) — "Mature"

**Theme**: Enterprise readiness, community governance, ecosystem integration.

**Planning started (2026-08-08)**: Q4 milestone #3 created; tracking issue #1159 open. **All 9 Q4 goals now tracked** (#1167 branch protection, #1168 governance, #1186 release automation, #1187 package signing/SBOM). Stale dependency refs (#306/#307/#212/#301 closed) still flagged in #1159 — new trackers needed for Tacklebox decoupling and Upstream snapshot automation. Extended 08-08 evening: adoption metrics (#1174) and variant lifecycle policy (#1175) added as strategist-owned goals.

| Goal | Owner | Dependencies |
|------|-------|--------------|
| Tacklebox decoupling | architect | #306 (closed — needs new tracker) |
| Upstream snapshot automation | ci-maintainer | #307 (closed — needs new tracker) |
| Branch protection + required CI | strategist | CI health, #1167 |
| Supply chain hardening | sec-check | #212, #301 (closed — needs new tracker) |
| Release automation | ci-maintainer | CI health, VERSIONING.md, #1186 |
| Community governance model | strategist | #1168 |
| Package signing / SBOM | sec-check | Supply chain, #1187 |
| Bonito (Fedora 44) GA carryover | ci-maintainer | #272 |
| Redfin (RHEL 10) alpha GA | ci-maintainer | #609 |
| Fedora 45 base readiness | ci-maintainer | #1171 |
| Adoption metrics / usage telemetry | strategist | #1174 |
| Variant lifecycle policy (Beta→Stable exit criteria) | strategist | #1175 |

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
*Generated by strategist agent at ACMM L6. Updated 2026-08-10 for Q3 checkpoint + desktop parity. Signed-off-by: hanthor-hive-agent[bot] <290068839+hanthor-hive-agent[bot]@users.noreply.github.com>*
