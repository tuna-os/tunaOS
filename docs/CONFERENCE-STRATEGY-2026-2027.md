# Conference strategy: Q4 2026 and Q1 2027

Preparation for [#3017](https://github.com/tuna-os/tunaos/issues/3017).
Prioritize a technical Q1 session at FOSDEM and use Q4 to prepare proposals.
Treat SCaLE as a Q2 extension with a Q4 deadline. Speaker consent, travel
approval and portal submission remain human tasks. This plan makes no speaker
commitments and records no submissions or acceptances.

## Research record: 2026-10-23

This record cites sources from October 23. The dates in
#3017 are estimates; use the organizer sources below when you select a CFP.

- **Flock to Fedora 2026:** [Fedora's event record](https://www.fedoraproject.org/flock/2026/)
  gives June 14–16 in Prague. The [CFP](https://cfp.fedoraproject.org/flock-to-fedora-2026/cfp)
  closed February 8, 2026 after an extension. This is a past event, outside
  Q4. Fedora contributors remain the audience for a future edition.
  Do not carry the September/October estimate forward.
- **Linux Plumbers 2026:** the [organizer overview](https://lpc.events/)
  gives October 5–7 in Prague. It has already ended. For a future proposal, identify a concrete systems problem.
  Discuss the evidence boundaries between image composition and boot verification.
  This record establishes no 2027 deadline.
- **GNOME Conference / GUADEC 2026:** the [GNOME event record](https://events.gnome.org/event/306/)
  gives July 16–21 in A Coruña. Count GUADEC once; the issue identifies no
  separate event behind “GNOME Conference.” This is a past event, outside Q4.
  A future GNOME proposal should focus on desktop session validation across
  bases, with a reproducible example.
- **KDE Akademy 2026:** the [organizer page](https://akademy.kde.org/2026/)
  gives September 19–24 in Graz. This is a past event, outside Q4. For a future KDE proposal, focus on Plasma integration findings that upstream
  developers can use. This record establishes no future CFP date.
- **AlmaLinux Connect:** this research found no dated 2026/2027 conference or CFP
  on the [AlmaLinux site](https://almalinux.org/). Retain as an unconfirmed
  lead, not a submission target with an invented deadline. An organizer must announce the event before a proposal owner selects a slot.
- **OSSNA:** the [official announcement](https://events.linuxfoundation.org/open-source-summit-north-america/)
  gives May 17–19, 2027 in Vancouver. This is Q2, not Q1. The page supplies
  no CFP deadline. Keep it as a later general Linux/platform audience target.

## Submission priorities

1. **FOSDEM 2027, January 30–31, Brussels (Q1).** Consult the
   [accepted devroom list](https://fosdem.org/2027/news/accepted-developer-rooms/).
   Find the CFP for Image-Based Linux and Boot Integrity, Containers, or
   Distributions. Room calls have their own deadlines; the announcement
   does not establish those deadlines. Prefer the room whose call matches
   the technical lesson and submit once, subject to its rules. The
   [main-track call](https://fosdem.org/2027/news/call-for-main-track/)
   closes November 16, 2026 and offers 25- or 50-minute slots including
   questions. That deadline applies to main track only. Use main track only
   if the talk meets its broad-audience criteria. Confirm the portal's exact
   cutoff and time zone before you schedule submission.
2. **SCaLE 24x, April 1–4, 2027, Pasadena (Q2 extension):** the
   [official CFP](https://www.socallinuxexpo.org/scale/24x/cfp) closes
   November 1, 2026; notifications begin December 1. The call needs
   speakers to attend in person and does not offer financial assistance. Confirm
   attendance costs before you submit. Its Systems & Infrastructure topic
   fits an operator-focused talk; Cloud Native Days includes atomic OSes.
   Confirm the selected track's submission route. The published date does
   not specify a cutoff time zone; resolve that in the portal.

The named targets offer no verified Q4 slot after October 23.
A proposal does not guarantee a Q1 appearance. If no
willing speaker can attend an eligible event, keep the material for a later CFP.
Do not submit under an assumed identity.

## Proposal material and ownership

Reuse [the FOSDEM draft](CFP-FOSDEM-2027.md),
[the SCaLE draft](CFP-SCALE-24X.md) and [demo shot list](CFP-DEMO-SCRIPT.md)
from [#1135](https://github.com/tuna-os/tunaos/issues/1135). Their older
claims need the [content claim checklist](CONTENT-CLAIM-CHECKLIST.md) before
submission. Replace estimated event details with the organizer calls above.
[PR #3618](https://github.com/tuna-os/tunaos/pull/3618), for
[#2887](https://github.com/tuna-os/tunaos/issues/2887), adds two architecture
abstracts and slide outlines. Coordinate with that work and reuse its abstracts. This strategy does not depend on its merge.

Suggested proposal adaptations:

- **FOSDEM:** “One matrix, many desktops: build success and session verification.”
  Trace primary configuration through the
  resolver, installer and verification contract. Show one reproducible
  failure and its check. This gives distribution contributors a reusable
  method for multi-base bootc desktops.
- **SCaLE / later OSSNA:** “Reviewable desktop infrastructure with bootc.”
  Trace a configuration change to an image. Explain the difference between payload and persistent
  state. Show a rehearsed update/recovery example and a bounded pilot checklist. Limit the demo to a named artifact and state its limitations.

Do not copy the issue's general claims about production readiness or adoption.
Use [verification criteria](GREEN-CRITERIA.md) for readiness evidence and
omit fleet sizes, tool availability or hardware claims without sources.

Proposed responsibilities (each person must consent before assignment):

| Event | Proposal owner to recruit | Speaker to confirm | Next action |
|---|---|---|---|
| FOSDEM | Contributor familiar with resolver and verification | That contributor, or a consenting maintainer co-speaker | Select devroom call and adapt the technical draft |
| SCaLE | Contributor familiar with image updates and recovery | A consenting speaker able to attend Pasadena | Confirm travel feasibility before November 1 |
| Future Flock / GNOME / KDE / AlmaLinux / OSSNA | Contributor working in the relevant integration area | Confirm after organizer announcement | Find a dated call before scheduling a proposal |

James Reilly (@hanthor), listed in [MAINTAINERS.md](../MAINTAINERS.md), is a
candidate to coordinate recruitment, not an assigned speaker. Record each
volunteer's explicit acceptance in #3017. Do not infer consent or availability
from commit history. Get the bio, affiliation and consent to record
from the speaker. Keep contact details and portal credentials private.

## Tracking and review cadence

Use #3017 as the strategy ledger and link #1135/#2887 for shared submissions.
During Q4 CFP preparation, the proposal owner should review the
call each week and before submission. Once submitted, review
notifications weekly and update the ledger when the organizer responds.
Keep status in the issue ledger.

Copy this record into an issue comment for each selected event:

```text
Event / organizer CFP URL:
Event dates and location:
Exact deadline, time zone and source (checked YYYY-MM-DD):
Proposal owner / consent link:
Lead speaker and co-speaker / consent link:
Abstract revision, track, duration and required fields:
Travel/budget decision and recording terms reviewed:
State: researching | preparing | submitted | accepted | declined | withdrawn
Submission date and public-safe receipt reference:
Notification date / next check:
Accepted session URL and speaking date/time/time zone:
Deck, rehearsal artifact and fallback recording:
Post-event slides/recording and aggregate feedback:
```

Only move to `submitted` with a receipt, and to `accepted` with an organizer
notification or session page. Submission needs the speaker's authorized
account. After acceptance, rehearse against a named artifact and capture an
offline demo. After the event, link public materials and summarize attendee
questions and consented follow-up requests. Report observations. Do not attribute unrelated changes in adoption or star counts to the talk.
