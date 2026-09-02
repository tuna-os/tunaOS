# TunaOS Adoption Metrics Plan

**Last updated**: 2026-08-10 | **Owner**: strategist (snapshot), ci-maintainer (R2/Releases data), guide (publishing)
**Tracking**: [tunaos#1174](https://github.com/tuna-os/tunaos/issues/1174)

---

## Why

tunaOS ships 179+ downloadable ISOs across 9+ variants × 5 desktops, yet has
**zero usage telemetry**. Roadmap themes (Q3 "Expand", Q4 "Mature") are executed
without evidence of what users actually download, install, or keep. Enterprise
credibility (Redfin/RHEL #1123, FOSDEM 2027 CFP #1135) rests on demonstrable
adoption — today the only public signal is a star count that moved 55→56 in a
month.

This document defines *what* to measure, *where* the data comes from, *when* to
publish, and *how* the snapshot feeds roadmap decisions.

---

## Metric tiers (funnel)

| Tier | Metric | Source | Current baseline (08-10) | Target (Q4 2026, "Mature") |
|------|--------|--------|--------------------------|------------------------------|
| Discovery | GitHub stars / forks | GitHub API | 56 / 3 | ≥100 stars |
| Discovery | Docs site visits, top variant pages | Cloudflare analytics on tunaos.org | not measured | ≥1k visits/mo, variant-page ranking |
| Discovery | DistroWatch referral traffic | Cloudflare analytics referrer field, tunaos.org | not submitted yet — draft ready ([docs/DISTROWATCH-SUBMISSION.md](./docs/DISTROWATCH-SUBMISSION.md), tunaos#1333) | Submission live; referral share visible in the monthly snapshot |
| Download | ISO downloads by variant+desktop | R2 access logs (tunaos.org/download) | **not measured** | ≥1k ISO downloads/mo; variant ranking |
| Download | GitHub Release asset downloads | Releases API (resumed 08-09, #1106) | 0 (assets were empty shells) | assets present on all flavors; downloads counted |
| Install | Installs / successful boots | opt-in telemetry or boot-report gating | **not measured** | Q4 design decision (#577 GUI gate, #763) |
| Community | Open PRs from external contributors | GitHub API | 0 external contributors | ≥2 external contributor PRs merged |
| Community | Discussion posts, `good first issue` pickups | GitHub API | 0 starter issues (dead label, #1308) | ≥5 starter issues picked up |
| Community | **External** public adopters (production or evaluation), [ADOPTERS.md](./ADOPTERS.md) — excludes the maintainer and TunaOS's own infrastructure | Manual — PR from the adopting org, or outreach asking permission to list | 0 external entries (#1348) | ≥2–3 external evaluator/production entries |
| Community | Adoption-call conversion | GitHub Discussion + follow-up PRs | **not measured** | Record responses, consent-confirmed named entries, anonymous reports, and ADOPTERS.md PRs |

**Instrumentation order** (cheapest first):

1. **GitHub Releases download counts** — free API counter; requires non-gnome
   flavors to publish assets too (#1254 parity gap — scheduled matrix now
   covers gnome/kde/xfce/cosmic/niri, PR pending; watch the next few
   scheduled runs to confirm kde/xfce/cosmic/niri actually publish before
   counting this instrumentation step done).
2. **R2/Cloudflare access-log analytics** on tunaos.org/download — R2 already
   serves the ISOs; enable access logs + a dashboard (owner: ci-maintainer).
3. **Docs analytics** — Cloudflare Web Analytics on the Docusaurus site
   (one script tag; owner: guide).
4. **Install telemetry** — deferred to Q4 design decision; do not block 1–3.

---

## Cadence & publication

- **Monthly snapshot**, published in the ROADMAP **Community** section (first:
  **2026-11-01**, covering October — aligns with Q4 "Mature" opening).
- Snapshot format: downloads by variant × desktop (top 10), stars/forks,
  external-contributor PRs, release-asset presence per flavor,
  [ADOPTERS.md](./ADOPTERS.md) EXTERNAL production/evaluation entry count
  (the two self-entries — maintainer and TunaOS CI — are excluded; counting
  them would have met the >=2 target on the day it was written, #1348),
  adoption-call responses/conversion, and a one-line "variant ranking" that
  flags under-/over-performing editions.
- Ownership: **strategist** compiles; **ci-maintainer** supplies R2/Releases
  exports; **guide** publishes on tunaos.org/blog.

## Outreach evidence

The current outreach record is kept in
[docs/ADOPTION-OUTREACH-STATUS.md](docs/ADOPTION-OUTREACH-STATUS.md). A draft,
an intended recipient, or an ecosystem relationship is not an outreach result;
the monthly snapshot must record a sent date, public URL, response, or an
explicitly unattempted status.

## Decision linkage

Each snapshot must answer two questions for the roadmap:

1. Which variants/desktops justify the 40-cell nightly build fanout (#1106)?
2. Which variant pages need content investment (docs parity, #1294)?

A variant with <2% of downloads for two consecutive snapshots is a candidate
for **downgrade or retirement** in the next quarterly roadmap — unless there is
a documented strategic reason to keep it (e.g., enterprise channel #1123).

## Anti-goals

- No user-tracking cookies or invasive telemetry in the OS image.
- Download counts are a *proxy* for installs, not proof of use — do not
  over-claim adoption in external materials (FOSDEM CFP, enterprise outreach)
  beyond what snapshots show.

---

## Roadmap integration

Q4 2026 goal: **"Adoption metrics / usage telemetry"** (owner: strategist,
tunaos#1174) — first monthly snapshot published 2026-11-01 and Q4 target
metrics above met or explicitly re-baselined in the ROADMAP.

---
*Filed by strategist agent (ACMM L6 — full mode) — planning artifact for tunaos#1174.*
