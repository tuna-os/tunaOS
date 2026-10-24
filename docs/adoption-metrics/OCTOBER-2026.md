# October 2026 adoption snapshot — interim

**Month window:** 2026-10-01 00:00 UTC through 2026-11-01 00:00 UTC (exclusive).
**Snapshot date:** 2026-10-23. October is still in progress.
**Tracker:** [#3149](https://github.com/tuna-os/tunaOS/issues/3149).
**Final publication due:** 2026-11-01; strategist compiles, ci-maintainer exports, guide publishes.

This interim report records available evidence and the gaps for the first monthly
snapshot. It does not satisfy the final publication or adopter criteria.
The [generated census](2026-10-23-release-census.md) contains raw GitHub numbers,
a matrix of ISO assets, and links to the three retained ISOs.
Its [JSON receipt](2026-10-23-release-census.json) records the API endpoints,
UTC collection times, source commit, and config hash.

## Discovery

Use the dated star and fork counts in the census. These are totals at collection;
the August baseline in [the metrics plan](../../ADOPTION-METRICS.md) does not
establish an October 1 baseline. These totals cannot show growth within October.

| Metric | October evidence | Owner / remaining input |
|---|---|---|
| GitHub stars / forks | Dated totals in the census; monthly change unavailable | Strategist: collect again after October 31 |
| Docs visits / top variant pages | Unavailable; no provider export in this snapshot | Guide: export October Cloudflare Web Analytics totals and page paths |
| DistroWatch referrals | Unavailable; the outreach ledger has no sent or live submission URL | Outreach: verify the submission; guide: export referrals if live |

Unknown analytics values are not zero. The
[outreach ledger](../ADOPTION-OUTREACH-STATUS.md) holds the submission evidence.

## Download

The census has separate counts for ISOs, cards, SBOMs and other assets.
It includes all retained public releases, with prereleases excluded.
It does not filter by release date: an older ISO can have downloads in October.
One counter for an asset's lifetime cannot show when those downloads occurred.

| Metric | October evidence | Owner / remaining input |
|---|---|---|
| ISO downloads from R2 by variant and desktop | Unavailable; no dated access-log export in this snapshot | CI-maintainer: export October requests with byte/range and bot filters documented |
| GitHub ISO downloads | Lifetime counters only; see the census | Strategist: compare the same asset IDs across receipts; disclose absent October 1 counters |
| Top ten pairs | No positive GitHub ISO counter; monthly R2 ranking unavailable | CI-maintainer: supply complete R2 coverage before a monthly rank |

Combined ISOs contain several desktops. Count each download once under its
published group; do not assign one download to every desktop in that group.
Asset replacement or deletion breaks a counter delta. Preserve both receipts
and report the gap. Do not report a negative count or a zero for that asset.

## Community

At the census source commit, [ADOPTERS.md](../../ADOPTERS.md) has **0 external
production entries and 0 external evaluation entries**. The two development
entries are the maintainer and TunaOS CI. The ecosystem rows are dependencies.
None of those entries counts toward the external-adopter target.

| Metric | October evidence | Owner / remaining input |
|---|---|---|
| External human PRs merged in October | Unmeasured; the August contribution baseline is outside this window | Outreach: review dated PR URLs and human/external status; exclude bots and agents |
| Good-first-issue pickups in October | Unmeasured; labels alone do not prove a pickup | Outreach: record dated claim comments or linked contributor PRs |
| External adopters | 0 production / 0 evaluation entries at the source commit | Outreach: add only consent-confirmed public reports to ADOPTERS.md |
| Adoption-call conversion | No Discussion URL in the outreach ledger | Outreach: record the call URL, responses and consent separately |

PRs [#3605](https://github.com/tuna-os/tunaOS/pull/3605) and
[#3770](https://github.com/tuna-os/tunaOS/pull/3770) propose public-counter
collection and contributor reports. They are separate work under review.
A candidate author or merged PR does not prove adoption.

## Infrastructure and variant decisions

The census shows ISOs on GitHub for each variant in the config
across GNOME, KDE, XFCE, COSMIC and Niri. It distinguishes an absent ISO from
a desktop with no ISO build in the config. It does not infer coverage from
a release tag, an SBOM, or a release card. R2 availability is a separate measure.
Redfin is local-build only and outside the public matrix in the config.

**Variant rank:** no measured rank for October; do not mark any variant as
an under-performer or over-performer from the available counters.
The metrics plan needs two monthly snapshots before its less-than-2% retirement
rule can apply. The docs-page rank is also unmeasured, so it cannot yet guide
content investment.

## Finalize after October 31

1. Strategist: run the census again with a new dated path. Retain this receipt.
2. CI-maintainer and guide: attach October exports, UTC bounds, coverage, and filter rules.
3. Outreach: review October contributions and pickups, and verify adopter consent.
4. Guide: publish the final report in tuna-os/docs for tunaos.org/blog by November 1.
5. Strategist: add the verified post URL to ROADMAP and tracker #1637; keep #3149 open until its criteria hold.

```bash
GH_TOKEN="$GH_TOKEN" python3 scripts/release-asset-census.py \
  --output docs/adoption-metrics/2026-11-01-release-census
python3 -m pytest -q tests/test_release_asset_census.py
```

The command keeps each earlier receipt. It fails if an API page fails.
It needs `gh` with `GH_TOKEN` and Python 3.10 or later.
The JSON receipt is enough to regenerate its Markdown with the script's
`render()` function, without another API request.
Use the [publication handoff PR](https://github.com/tuna-os/tunaOS/pull/3686)
for the general owner schedule and blog format.
