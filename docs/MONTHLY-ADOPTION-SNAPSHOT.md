# Monthly adoption snapshot: November 1 handoff

This is the publication plan for [#3038](https://github.com/tuna-os/tunaos/issues/3038)
and the [metrics plan](../ADOPTION-METRICS.md). The first report covers
**2026-10-01 00:00 UTC to 2026-11-01 00:00 UTC**, with the end excluded.
The publication date is **2026-11-01**. This plan is not a published snapshot.

## Schedule and owners

The roles below come from #3038. They describe work due, not completed work
or confirmation that a person has accepted a calendar event.

| Due (UTC) | Owner | Deliverable |
|---|---|---|
| October 25 | ci-maintainer | Attach Releases export and asset-presence evidence to #3038; state whether R2 logs cover the full month |
| October 25 | guide | Attach docs analytics export and coverage dates, or record that analytics are unavailable |
| October 25–31 | strategist | Prepare the [blog draft](templates/monthly-adoption-snapshot.md); link adopter consent, outreach responses and human-contribution evidence |
| November 1, after 00:00 | ci-maintainer | Supply final exports with collection times, source links and coverage gaps |
| November 1, after exports | strategist | Complete the report, check all totals against receipts and give the draft to guide in #3038 |
| November 1 | guide | Open the blog PR in tuna-os/docs, publish through that repository's normal review process, then verify the public page |
| November 1, after publication | guide | Link the live post from ROADMAP.md Community and #3038; record any delay and next action if publication is still pending |
| First day of each later month | same roles | Repeat for the prior UTC calendar month; link the previous report and retain its receipts |

Keep #3038 open until the live blog URL and ROADMAP link exist. A draft,
workflow artifact or proposed URL does not satisfy publication. If a deadline
slips, record the missing input, owner and next collection/publication date in
#3038. Publish available evidence with explicit gaps; do not delay all public
metrics for unavailable provider analytics.

## Collection contract

Store receipts for the public aggregates with the report. Each export must name the
source endpoint or query, UTC collection time, covered interval, filters and
source revision or workflow run. Do not attach access logs, IP addresses, credentials or private reports from
adopters to a public issue or PR.

[PR #3605](https://github.com/tuna-os/tunaos/pull/3605) proposes the public API
collector and a first-of-month 09:00 UTC workflow. It is a separate change;
check that it has merged and that the workflow has run on upstream before
using its artifact. Do not create a second collector or treat that PR as
proof of October coverage. If it is unavailable, ci-maintainer must supply exports from the API
under the same receipt rules below.

| Input | Owner | Required interpretation |
|---|---|---|
| Releases and assets | ci-maintainer | Paginate releases and assets. Retain asset ID, release URL, name, creation time and download count. Count ISO assets separately from checksums, signatures and other downloads. |
| Asset presence | ci-maintainer | Check Yellowfin, Albacore, Skipjack, Bonito and Redfin separately from GNOME/KDE/XFCE/COSMIC/Niri. These are variants and desktops, respectively. Check dated publishing runs for October; one present asset does not prove a month of stable publication. |
| R2 ISO requests | ci-maintainer | Export aggregate downloads by variant and desktop, with the query's success, range-request, bot and CI filters. Record partial coverage and combined-desktop ISO groups. |
| Docs visits and referrals | guide | Export visits and variant-page ranking, plus DistroWatch referrals if measured. Name the instrumented host, path filters and start date. Missing instrumentation means unavailable, not zero visits. |
| Stars and forks | strategist | Record counts at collection time. Claim a monthly change only with a comparable opening receipt. |
| Human contribution census | strategist | List merged PR URLs and merge dates inside the interval. Verify external human authors; exclude maintainers, bots and agent accounts. Report PR and unique-human counts separately, with repeat contributors. Record any unverified authors separately. |
| External adopters | strategist | Check ADOPTERS.md at a recorded commit. Count consent-confirmed external production and evaluation entries separately; exclude maintainer and TunaOS CI entries. Do not infer OS use from a contribution. |
| Adoption-call conversion | strategist | Link sent calls and responses from the outreach ledger. Separate responses, named entries with consent, anonymous reports and adopter PRs. Do not count a prepared draft as a sent call. |

GitHub asset counters are **lifetime counters**. A total at the end of the month cannot
show downloads for October. For a monthly delta, compare counters for the same
asset IDs at both boundaries. Note deleted or replaced assets as a coverage
gap; a new ID is not continuity of an old asset.

Without a receipt from the start of the month,
label the result as lifetime downloads observed at collection time. State
that downloads for October are unavailable. If collection starts in late October, it cannot cover the full month.

Keep R2 and Releases totals separate unless the sources prove requests do not
overlap. Downloads are a proxy for interest, not installations or people.
Combined-desktop media cannot support per-desktop estimates without another
source. The [weekly countme reports](adr/0011-private-adoption-metrics.md) are
a separate aggregate signal, not download counts or unique users; preserve
the published precision and suppressed values if cited.

## Report and publication checks

1. Copy the template into a report draft. Replace every field with a value
   linked to a receipt, or with an explicit unavailable status and owner.
   Keep a complete aggregate CSV/JSON beside any top-ten table. Generate
   tables from the export; do not maintain a second table of live counters.
2. Rank only comparable variant data with a stated denominator and coverage.
   If coverage is incomplete, state that the data cannot support a rank across variants.
   A single report does not meet the metrics plan's two-month, below-2%
   retirement criterion. Explain what evidence is still needed for build
   allocation and variant-page investment.
3. Give guide a one-page report with receipt links in #3038. The public blog
   lives in [tuna-os/docs](https://github.com/tuna-os/docs), not this folder.
   Follow that repository's contribution and blog conventions for the PR.
4. After the blog is live, verify the actual URL and add it to the Community
   section of ROADMAP.md. Keep the handoff link as the procedure; add the
   dated post link as evidence. Record the docs PR and public URL in #3038.
5. Retain the public receipts beyond any workflow artifact expiry, then
   repeat the handoff on December 1 for November. Record any source or
   filter changes so the next comparison can explain a break in series.
