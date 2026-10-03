# TunaOS Adoption Metrics Plan

**Last updated**: 2026-10-03 | **Owner**: strategist (snapshot), ci-maintainer (R2/Releases data), guide (publishing)
**Tracking**: [tunaos#1174](https://github.com/tuna-os/tunaos/issues/1174), [tunaos#2819](https://github.com/tuna-os/tunaos/issues/2819)
**Snapshots**: [latest report and dated source data](docs/adoption-metrics/README.md)

---

## Why

tunaOS ships 179+ downloadable ISOs across 9+ variants × 5 desktops, yet has
**zero usage telemetry**. Roadmap themes (Q3 "Expand", Q4 "Mature") are executed
without evidence of what users download, install, or keep. Enterprise
credibility (Redfin/RHEL #1123, FOSDEM 2027 CFP #1135) rests on demonstrable
adoption — today the only public signal is a star count that moved 55→56 in a
month.

This document defines *what* to measure, *where* the data comes from, *when* to
publish, and *how* the snapshot feeds roadmap decisions.

---

## Metric tiers (funnel)

| Tier | Metric | Source | Baseline source | Target (Q4 2026, "Mature") |
|------|--------|--------|-----------------|------------------------------|
| Discovery | GitHub stars / forks | GitHub API | [generated snapshot](docs/adoption-metrics/README.md) | ≥100 stars |
| Discovery | Docs site visits, top variant pages | Cloudflare analytics on tunaos.org | export not connected | ≥1k visits/mo, variant-page ranking |
| Discovery | DistroWatch referral traffic | Cloudflare analytics referrer field, tunaos.org | export not connected | Submission live; referral share visible in the monthly snapshot |
| Download | ISO downloads by variant+desktop | R2 access logs (tunaos.org/download) | export not connected | ≥1k ISO downloads/mo; variant ranking |
| Download | GitHub Release asset downloads | Releases API | [generated snapshot by asset class](docs/adoption-metrics/README.md) | ISO assets present and downloads counted without including cards or SBOMs |
| Install | Installs / successful boots | opt-in telemetry or boot-report gating | not collected | Q4 design decision (#577 GUI gate, #763) |
| Community | Merged PRs from external human contributors across tuna-os | GitHub API | [generated non-bot-account proxy](docs/adoption-metrics/README.md); GitHub account type does not verify human authorship | ≥5 merged PRs from ≥3 humans, including one repeat contributor |
| Community | Discussion posts | GitHub API | [generated previous-month snapshot](docs/adoption-metrics/README.md) | sustained monthly activity |
| Community | **External** public adopters (production or evaluation), [ADOPTERS.md](./ADOPTERS.md) — excludes the maintainer and TunaOS's own infrastructure | ADOPTERS.md | [generated snapshot](docs/adoption-metrics/README.md) | ≥2–3 external evaluator/production entries |
| Community | Adoption-call conversion | GitHub Discussion + follow-up PRs | not yet attributable by the public APIs | Record responses, consent-confirmed named entries, anonymous reports, and ADOPTERS.md PRs |

**Instrumentation order** (cheapest first):

1. **GitHub Releases download counts** — automated monthly by
   `scripts/generate-adoption-snapshot.py`. The collector separates ISO, SBOM,
   release-card, and other assets so an SBOM fetch cannot inflate the download
   proxy. Counters are cumulative; consecutive snapshots provide the monthly
   delta.
2. **R2/Cloudflare access-log analytics** on tunaos.org/download — **not
   connected**. R2 serves the ISOs, while the baseline found only three old
   ISO assets across 232 GitHub Releases. Until the account owner supplies an access-log export,
   neither total ISO downloads nor variant ranking can be reported.
3. **Docs analytics** — **not connected**. Cloudflare Web Analytics needs an
   account-owner export before the monthly collector can include visits or
   referral fields.
4. **Install telemetry** — deferred to the Q4 consent decision; do not infer
   installs from downloads.

---

## Cadence & publication

- **Monthly snapshot**, generated on the first day of each month in
  [`docs/adoption-metrics/`](docs/adoption-metrics/). The 2026-10-03 baseline
  covers September community activity and establishes cumulative counters;
  the 2026-11-01 run will provide the first counter delta while covering
  October activity.
- Snapshot format: downloads by variant × desktop (top 10) when the R2 export is available, stars/forks,
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

### Contribution evidence is not adoption evidence

The 2026-08-14 docs merges establish a real external-contribution channel and
are useful leading evidence for the Hacktoberfest funnel. They do not establish
that the authors use TunaOS. Keep the contribution count separate from
production/evaluation entries in `ADOPTERS.md`; only a consent-confirmed report
belongs in the adopter funnel.

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
