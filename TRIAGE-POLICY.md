# tunaOS Issue Triage Policy

**Status**: ADOPTED — merged via [#1438](https://github.com/tuna-os/tunaOS/pull/1438) on 2026-08-13
**Owner**: tuna-os (hanthor) / strategist
**Tracks**: #1195 (this finding), #1168 (Q4 community governance goal)

## Purpose

#1195 found the project at ~341 open issues with a ~99% SLA violation rate —
a queue too large for the single maintainer (bus factor: #1095) to act on,
and noisy enough to bury real signal from roadmap planning (#1159, #1167,
#1168, #1186, #1187) and contributor onboarding (#1134). This document adopts
the triage policy #1195 proposed, adjusted where live queue data (below)
showed the original mechanism wouldn't fire.

## Current state (verified 2026-08-13, GitHub search API)

- **104 open issues**, down from 341 at #1195's filing (2026-08-08) — the
  queue has already shrunk substantially through the hive's own ongoing
  triage/closure work, not through a documented policy.
- **89 open issues carry no milestone**; 15 are milestone-attached.
- **0 open issues have gone 60+ days without an update.** This is the one
  place live data changed the plan: #1195's "close-stale pass" assumed a
  calendar-age signal (`updated_at` > 60 days), the same mechanism GitHub's
  `actions/stale` bot uses by default. It would never fire here — Hive agents
  touch nearly every open issue routinely (comments, re-verification,
  corrective findings), so nothing goes calendar-stale even when the
  underlying finding is resolved or superseded. A stale-bot keyed on
  inactivity would sit permanently idle and give false confidence that
  "nothing needs triage." The policy below replaces that mechanism.

## Policy

### 1. Milestone-only signal (adopts #1195 recommendation #4)

A **milestone-attached issue is the actionable roadmap**; ROADMAP.md tracks
only milestone-attached work. Everything else is backlog: worth keeping
(it may be a real, valid finding — see the numbering-collision and stale-doc
fixes this policy's own drafting process turned up), but not a claim on
near-term capacity. This formalizes what ROADMAP.md already does in practice
today.

### 2. Resolution-verified closure, not calendar-age closure

Since nothing in this queue goes calendar-stale, "close-stale" here means:
**before trusting a bot-filed finding, verify against current repo state**,
not against how long ago it was filed. Every hive-contributor task in this
project already follows this discipline (grep/API/live-CI verification
before acting — see #1179, #1180, #1183, #1187 for recent examples where the
live state had already resolved, partially resolved, or diverged from the
original finding). This policy makes that the documented default instead of
an implicit convention:

- A bot-filed finding whose cited evidence (file:line, API response, CI run)
  no longer matches current repo state should be closed with a comment
  citing what changed, not left open on the strength of its original filing.
- A finding that turns out to be a subset or duplicate of another open
  issue/PR should be closed pointing at the surviving one (the dedup pass,
  below), not left open in parallel.
- A finding still valid but genuinely out of scope for available tooling
  (needs a live secret rotation, a GitHub App permission this org's
  contributor agents don't have, a maintainer-only repo-settings change)
  gets a comment recording that boundary, and stays open — it is real
  backlog, not noise, and closing it would just lose the finding.

### 3. Dedup pass (adopts #1195 recommendation #2)

Bot-generated findings that name the same root cause (the #1186/#1187
pattern #1195 itself cites) should collapse onto one tracker issue. When
triaging a new bot-filed issue, search for existing open issues covering the
same file/workflow/repo before treating it as independent work.

### 4. SLA re-baseline by priority tier (adopts #1195 recommendation #3)

Replace the flat, universally-violated SLA with tiers keyed to what's
actually being tracked:

| Tier | Definition | Target response |
|---|---|---|
| **P0** | Milestone-attached, blocking a Q-checkpoint (e.g. #1299) | 48h |
| **P1** | Milestone-attached, not blocking a checkpoint | 7d |
| **P2** | Backlog (no milestone) — includes most bot-filed findings | 30d, best-effort |

"Response" means triage (verify, act, or comment), not resolution — matching
the existing PR-review service goal in COMMUNITY.md ("reviewed within 48
hours" is a goal, not an automatic promise). P2's 30-day target is
aspirational given the current 89-issue backlog and single-maintainer bus
factor; it exists to make violation *visible and countable* again, which a
flat 100%-violated SLA no longer does.

## What this policy does not do

It does not authorize automated closure. No workflow in this repo
auto-closes issues on this policy's authority; `actions/stale`-style
automation was evaluated (see "Current state" above) and rejected as the
wrong mechanism for how this queue actually behaves. Triage stays a
verify-then-decide human/agent action per issue, using the criteria above.

---
*Filed by strategist agent (ACMM L6 — full mode)*
