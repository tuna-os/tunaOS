# Q4 production adopter sprint

Tracker: [#3146](https://github.com/tuna-os/tunaOS/issues/3146).
Plan: [Q4 adoption milestones](../../Q4-ADOPTION-PLAN.md).
Target: identify and engage 3–5 teams by 2026-11-01, then seek a verified
production report and an approved case study. This plan proposes work dates;
it records no completed contacts or commitments from the prospects.

## Scope and evidence

This shortlist has five projects or teams to approach. Selection
shows a possible fit; it does not show interest, a partnership, or use of
TunaOS. The first question is whether a team has a deployment need and a
person who can own an evaluation. A referral or a technical review alone
does not qualify the project as a production prospect.

Use [ADOPTERS.md](../../ADOPTERS.md) for verified reports and the
[outreach ledger](../ADOPTION-OUTREACH-STATUS.md) for contact evidence.
Do not copy live counts into this plan. Run the monthly collection defined in
[ADOPTION-METRICS.md](../../ADOPTION-METRICS.md) for the checkpoint.

The issue calls Discussion #93 the adoption call. A public API read on
2026-10-23 identifies it as
[“Will TunaOS run on a ‘Copilot’ ARM PC?”](https://github.com/orgs/tuna-os/discussions/93).
Do not route adopter replies there. The
[adoption call](../ADOPTION-CALL.md) defines the Show-and-tell publication
workflow; [#3183](https://github.com/tuna-os/tunaOS/issues/3183) tracks that
launch. Until a maintainer records its URL, use the
[adoption-request form](https://github.com/tuna-os/.github/issues/new?template=adoption.yml)
from ADOPTERS.md.

## Five proposed contacts

Research date: 2026-10-23. Recheck the contact paths before you send a message.
The order reflects technology in common and access to a team. It does not
measure the likelihood of adoption. Each row proposes one first conversation.

| Priority / team | Source and public contact path | Proposed request and qualification |
|---|---|---|
| 1 — Universal Blue / Bluefin community | The [Universal Blue site](https://universal-blue.org/#community) describes bootc image work and links its Discourse community. Ask a community moderator which collaboration thread fits. | Ask whether an independent team wants to evaluate a TunaOS workstation for its own work. Offer a comparison of image maintenance and update workflows. Request a deployment owner and use case before a demo. Coordinate with [#2886](https://github.com/tuna-os/tunaOS/issues/2886) and [#3115](https://github.com/tuna-os/tunaOS/issues/3115), rather than sending a second partnership pitch. |
| 2 — AlmaLinux Atomic SIG | The [official SIG page](https://wiki.almalinux.org/sigs/Atomic.html) describes its desktop bootc images, links Mattermost, and lists SIG members. Use that public channel through the existing project relationship. | Ask if a team outside TunaOS wants an Albacore or Yellowfin evaluation for a real workstation need. Start with a comparison against the SIG's own desktop work. Reuse the [AlmaLinux engagement effort](ALMALINUX-ENGAGEMENT.md) and [#3016](https://github.com/tuna-os/tunaOS/issues/3016); do not claim that AlmaLinux lacks a desktop project or promise a regular meeting. |
| 3 — Fedora KDE SIG / Kinoite team | The [Fedora Kinoite community page](https://fedoraproject.org/atomic-desktops/kinoite/community/) identifies the KDE SIG and lists its forum and `#kinoite:fedoraproject.org` Matrix room. Ask for the right collaboration contact there. | Ask whether a willing team has a Bonito KDE test workstation use case and can compare its update and desktop workflow. Use the [Fedora readiness handoff](../FEDORA-OUTREACH-READINESS.md) before offering media. Fedora contribution or use of Kinoite does not imply use of Bonito. |
| 4 — KDE development community | [KDE's developer contact guide](https://develop.kde.org/docs/getting-started/building/help-developers/) lists `#kde-devel:kde.org`, the Development forum, and `kde-devel`. Ask for the relevant team in one of those channels. | Ask whether a team needs a separate EL desktop test machine and would evaluate a KDE flavor. Request its required applications and hardware before choosing a cell. If this reaches the same people as the Fedora row, keep one contact and count one deployment. |
| 5 — BuildStream project / external integrators | [BuildStream's own guide](https://docs.buildstream.build/master/main_about.html) describes system integration and lists `#buildstream:matrix.org` and `dev@buildstream.apache.org`. Start with a technical fit question in one channel. | Ask whether an external integrator has a TunaOS workstation evaluation need. Offer an exchange about build-host requirements. Interest in BuildStream, Tromsø, or XFCE Linux alone is not TunaOS adoption; route sibling-only feedback to that project and seek another prospect. |

The AlmaLinux roster lists `hanthor`, the TunaOS maintainer. This gives a
possible introduction path, not an external adopter: a report must come from
an independent deployment and an authorized representative. Likewise,
contributors' employers, GitHub profiles, stars, and upstream commits do not
establish organizational use or permission to contact an employer.

These projects already have their own systems. Offer a bounded evaluation or
ask for a referral; do not ask a project to replace its distribution. If a
row has no willing deployment owner, record the outcome and seek an opt-in
team through the public adopter call. Education and research remain a later
pool through the [education brief](../EDUCATION-PITCH.md). Add a specific lab
only when it has a public contact and a stated need.

## First-contact copy for review

An authorized project representative should adapt this copy to the channel
and the row's request. Follow the external-account handoff in the
[agent guide](../AGENT_GUIDE.md#community--outreach-initiatives-687).

> Hello [team], I contribute to TunaOS, an image factory for bootc desktops.
> Your work on [specific project] suggests a useful technical comparison.
> Would a team like to evaluate [variant and desktop] on a test
> workstation for [use case], or is there a better place to ask? We can first share
> the candidate's verification results and limitations, then arrange a short
> demo if useful.
>
> Teams already using TunaOS can reply through [actual adoption-call URL or
> adoption-request form]. Any public listing or quote needs your approval.

Teams can decline adoption or a testimonial.

Before you send a message, replace every placeholder, check the
[content claims](../CONTENT-CLAIM-CHECKLIST.md), and attach evidence for the
exact candidate, hardware, and desktop. A configured variant in `tunaos.toml`
does not prove a usable image. Check the
[green criteria](../GREEN-CRITERIA.md) and current candidate results before
making an evaluation offer. Propose a test machine or VM first; an update,
rollback, or install demonstration must use a tested candidate and disposable
test data. Do not promise production readiness, support, or delivery dates.

## Work dates and follow-up

Proposed roles: outreach prepares and records contacts; the maintainer names
an authorized sender; guide helps with candidate evidence and interviews;
strategist reports the checkpoint. These roles do not imply that someone has
accepted an invitation or that an external message has been sent.

| Due | Proposed action | Required output |
|---|---|---|
| 2026-10-25 | Outreach and maintainer check existing conversations, choose a sender, and review the five requests. | One contact owner per team; candidate evidence or a fit-only question where evidence is absent. |
| 2026-10-27 | Authorized sender approaches 3–5 teams through suitable public or existing warm channels. | Dated thread links in the outreach ledger; channel permission before posting a full invitation. |
| 2026-10-30 | Outreach acknowledges replies and offers interested teams a 20-minute demo or office-hour slot. | Agreed time and scope, or an explicit decline/no-response record. No meeting is claimed until it happens. |
| 2026-11-01 | Strategist reviews each deliverable in #3146 with links to contact records and approved artifacts. | Separate totals for contacted teams, replies, evaluations, production entries, and approved stories. State any missed target without changing its definition. |
| 2026-11-06 | Sender follows up once on unanswered contacts, at least seven days after the first message. | Same-thread reminder or closure as no response. Stop on a decline; do not cold-DM or contact several members of one team. |
| 2026-11-13 | Guide checks active evaluations for blockers and an optional interview. | Reported outcome, linked technical issues, next agreed date, and consent scope. Close inactive conversations without counting adoption. |
| 2026-11-15 | Strategist includes remaining prospects in the Q4 health check. | For each willing team: owner, evidence link, next step/date, or reason for closure. |

For every contact, record the team, sender, first-contact date, public thread,
response category, next action/date, and any follow-up PR in the ledger.
Private reports need permission before public summaries; do not commit contact
details or private transcripts. A template for a public record is:

```text
Team:
Sender and contact date:
Public evidence URL:
Outcome: no response / declined / interested / evaluation / production report
Deployment owner and scope, if volunteered for publication:
Next action, owner, and date:
Approved listing or story URL / PR, if any:
```

## Completing the evidence deliverables

For a willing evaluator, guide asks about the workload, chosen variant and
desktop, start month, hardware, update experience, and problems. Capture what
the team ran and the limits of the report. Use the case-study
program in [#3020](https://github.com/tuna-os/tunaOS/issues/3020).
[PR #3675](https://github.com/tuna-os/tunaOS/pull/3675) proposes its template.
An evaluation story can meet the issue's
any-tier testimonial goal, but cannot meet its production goal.

Before publication, get an authorized representative's approval of the
exact final text. Get separate permission for a quote, a case study, and
an ADOPTERS.md entry; approval of one does not grant all three. Link the
approval and the published artifact from #3146. If approval is private, a
maintainer must confirm the permitted public evidence without disclosure of the
private exchange.

Add a Production Users row only after the representative confirms use in
production. Confirm the public name, use case, variants/desktops, start month,
and consent to the exact entry. Keep evaluations in their own category. One
deployment seen through two communities counts once; internal use and
sibling-only use do not count as external TunaOS production use.

Keep #3146 open until all four deliverables have evidence:

- Contacts with 3–5 prospects.
- A completed and approved testimonial or case study.
- A verified entry in Production Users.
- A follow-up record for the other prospects.

Prepared requests alone do not meet those outcomes.
