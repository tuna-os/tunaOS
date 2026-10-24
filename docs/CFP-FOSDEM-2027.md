# FOSDEM 2027 — CFP draft

Draft for a speaker to review and submit with their consent. Track preparation
and outcomes in [#3179](https://github.com/tuna-os/tunaos/issues/3179). Earlier
preparation is in [#1135](https://github.com/tuna-os/tunaos/issues/1135). This
document records no submission or acceptance.

## Organizer research — 2026-10-24

[FOSDEM's main-track call](https://fosdem.org/2027/news/call-for-main-track/)
confirms **January 30–31, 2027, Brussels**. This replaces the February 6–7
estimate in the draft. Main track closes **November 16, 2026** and offers 25- or
50-minute slots including questions. This deadline applies only to main track.
The call needs English, FOSS content and agreement to publication under FOSDEM's
CC-BY terms and its code of conduct.

The [announcement of accepted
rooms](https://fosdem.org/2027/news/accepted-developer-rooms/) lists
**Image-Based Linux and Boot Integrity**, **Containers**, **Distributions**, and
**Virtualization and Cloud Infrastructure**. Prefer Image-Based Linux and Boot
Integrity for the proposal below; Containers is an alternative if its call fits.
The announcement does not establish deadlines for room submissions, durations or
abstract limits. Record the selected room's own call before submission. Do not
assume a room named “bootc” or “Desktops.”

For main track, first assess the call's broad-audience requirement. A room
proposal should not be sent there solely because its deadline is known.

## Talk title

**Immutable enterprise desktops with bootc: what an image rollback restores**

## Abstract

What changes when a desktop operating system becomes an OCI image? Operators can
review the build as infrastructure. For recovery, they must understand which
state belongs to the image and which state persists outside it.

This session uses TunaOS, an open-source image factory for bootc desktops, to
explore that boundary on an Enterprise Linux base. We trace a desktop choice
from primary configuration through package selection and image assembly. We then
update and recover an artifact with a known identity. The walkthrough connects a
review of source to the system a user boots. A successful build does not prove
that every desktop works.

A recorded demonstration will compare the booted and staged image before and
after an update. We will reboot into the new deployment and return to the prior
deployment. We will show data that persists outside the image. An
operating-system rollback does not promise to reverse application data or every
configuration change. The speaker will identify the tested artifact and
rehearsal evidence, and explain the limits of that example.

We finish with questions for a bounded desktop pilot. Which image did we test?
Does its desktop session start? How did we exercise recovery? Which checks must
we repeat on the intended hardware?

Attendees leave with a source walkthrough and a recovery checklist they can
adapt to their own image-based systems. Linux administration and basic OCI
knowledge are useful; Kubernetes is not required.

## Outline and demo video

Proposed 25-minute version, including questions; adapt to the selected room:

1. Payload and persistent state: 4 minutes.
2. Configuration to image walkthrough: 6 minutes.
3. Recorded update, reboot and rollback: 5 minutes.
4. Verification criteria and pilot checklist: 5 minutes.
5. Questions: 5 minutes.

### Demo video outline (3-5 min, attach to CFP)

Use [CFP-DEMO-SCRIPT.md](CFP-DEMO-SCRIPT.md) as a guide for the update/rollback
portion. That runbook states that its author did not execute it; it is not
evidence of a successful demo. Rehearse on a disposable VM, capture before/after
digests, booted deployments and persistent-state observations, and retain an
offline video. Omit the Corral segment for this proposal. A separate Kubernetes
session needs its own verified demonstration and a suitable call.

## Evidence for the speaker

- [Primary configuration](../tunaos.toml), [flavor resolver](../scripts/resolve-flavor.sh)
  and [desktop installer](../build_scripts/desktop/install-desktop.sh): source walkthrough.
- [Roadmap](../ROADMAP.md): planned work; not evidence that a feature shipped.
- [Verification criteria](GREEN-CRITERIA.md) and [generated matrix evidence](MATRIX-STATUS.md):
  select a tested artifact for rehearsal; do not quote a fixed edition count.
- [Adopters and ecosystem dependencies](../ADOPTERS.md): upstream dependencies
  do not establish external adoption, partnership or endorsement.
- [Content claim checklist](CONTENT-CLAIM-CHECKLIST.md): apply before submission.

This replaces the earlier production-deployment and automatic-recovery claims.
Do not carry forward star counts, compliance language, lifecycle guarantees or
an assumed CNCF relationship. The [CNCF pitch](CNCF-BOOTC-SHOWCASE.md) is
separate outreach; an upstream dependency is not a confirmed relationship.

## Submission and response record

Use #3179 as the ledger for this proposal and the [SCaLE
adaptation](CFP-SCALE-24X.md). Coordinate with [PR
#3713](https://github.com/tuna-os/tunaos/pull/3713) (architecture abstracts) and
[PR #3778](https://github.com/tuna-os/tunaos/pull/3778) (conference strategy)
before submission to avoid duplicate sessions.

- [ ] A speaker volunteers, confirms attendance and supplies their own bio.
- [ ] Record room, call URL, exact deadline/time zone, format and portal fields.
- [ ] Review the abstract and complete the recorded rehearsal.
- [ ] The speaker reviews the terms for publication and submits through their authorized account.
- [ ] Record a public-safe receipt in #3179; keep private contact data out of GitHub.
- [ ] Record response and, if accepted, session URL, final slides and video.

Aim to submit 2–4 weeks before a verified deadline. For the November 16
main-track deadline, that target window is October 19–November 2; use it only if
main track is appropriate. Derive the room's schedule from its own call. Review
the ledger weekly and after each organizer response. A receipt establishes
submission; acceptance needs a response from an organizer or a link to a
published session.

Copy one record per proposal into #3179:

```text
Event / track / organizer call URL:
Deadline, time zone and source checked on:
Speaker and attendance consent link:
Abstract revision / duration / portal requirements:
Demo artifact and rehearsal evidence:
State: preparing | submitted | accepted | declined | withdrawn
Submission date / public-safe receipt:
Notification date / next review:
Accepted session URL / speaking date:
Slides / recording URL:
```

## Other season targets — research on 2026-10-24

[SCaLE 24x](CFP-SCALE-24X.md) is the immediate CFP priority and a Q2 event. Its
November 1 deadline is eight days away; the requested 2–4 week lead time has
passed. A speaker should evaluate it now. This preparation has missed the target
window for early submission.

For Australia, [Everything
Open](https://2027.everythingopen.au/programme/proposals/) confirms January
20–22 in Brisbane. Its call closed on September 20, 2026 at 23:59 AoE after an
extension. The older [draft](CFP-EVERYTHING-OPEN-2027.md) lists the superseded
September 6 deadline. Do not treat it as an open CFP or infer a separate
linux.conf.au 2027 call.

The [call for KubeCon
Europe](https://events.linuxfoundation.org/kubecon-cloudnativecon-europe/program/cfp/)
places the event in Barcelona, March 15–18, 2027; its October 11, 2026, 23:59
CEST deadline has passed. Do not submit a Corral proposal against that closed
call. [OSS
NA](https://events.linuxfoundation.org/open-source-summit-north-america/) is May
17–19 in Vancouver, outside Q1; that page supplies no CFP deadline. Reuse the
[OSS NA proposal](CFP-OSS-NA-2027.md) when a dated call is available.
