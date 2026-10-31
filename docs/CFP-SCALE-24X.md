# SCaLE 24x — CFP draft

Draft for a speaker to review and submit with their consent. Track preparation
and responses in [#3179](https://github.com/tuna-os/tunaos/issues/3179). This
adapts the [FOSDEM proposal](CFP-FOSDEM-2027.md) for Linux administrators. This
document records no submission, speaker commitment or acceptance.

## Organizer research — 2026-10-24

The [official CFP](https://www.socallinuxexpo.org/scale/24x/cfp) confirms
**SCaLE 24x, April 1–4, 2027, Pasadena**. It is a Q2 event with a Q4 CFP, not
SCaLE 22x in March as #3179 estimates. The deadline is **November 1, 2026**;
notifications begin December 1. The page gives no cutoff time zone. Resolve that
in the portal before submission.

Prefer **Systems & Infrastructure**. Cloud Native Days is an alternative for an
atomic-OS session; confirm its route before submission. The call requests a
title, short and long abstracts, track and level, plus speaker profiles. Each
new profile needs a name, email, photo and third-person bio of at most 1,000
characters.

Slots are about 45 minutes. Speakers must attend in person; they receive a
conference pass but no financial assistance. Review the linked speaker agreement
and code of conduct before submission.

## Talk title

**Desktop Linux at scale: atomic updates and rollback with TunaOS**

“At scale” describes the operational questions, not a measured TunaOS fleet.
Proposed level: intermediate Linux administration. No Kubernetes experience is
required.

## Short abstract

An image-based desktop changes how an operating system is built and updated, but
it does not remove persistent state or the need to test recovery. This TunaOS
walkthrough follows a configuration change to a bootc desktop image, then uses a
recorded update and rollback to build a practical pilot checklist.

## Long abstract

Desktop administrators need to know what changed, which machines received it,
and how to recover when an update causes trouble. A reviewable image of the
operating-system payload can help answer those questions. The operator must also
understand the state that remains outside the image.

This session follows a desktop configuration change through TunaOS's bootc image
factory. We examine the source inputs, image assembly and artifact identity
before moving into a recorded update and rollback exercise on a single
disposable VM. The demonstration will name the tested image and show the booted
deployment before and after reboot. We observe persistent files and application
state separately. Image rollback does not provide a complete backup or a system
for data recovery.

The second half turns that example into a rollout plan. We select a small pilot
group, test representative hardware and desktop sessions, and define recovery
criteria. We decide what evidence we need before expansion. TunaOS's
verification contract distinguishes a successful build from a desktop that
works. We also discuss the limits of a demonstration on one machine.

Attendees leave with a source walkthrough, a way to record artifact identity and
a checklist to evaluate updates and recovery in their own environment. The talk
is an engineering demonstration, with no claim of measured enterprise adoption
or automatic fleet recovery.

## Outline and materials

Proposed 45-minute session including questions:

1. Operator questions and state boundaries: 5 minutes.
2. Configuration change through image assembly: 10 minutes.
3. Recorded update/reboot/rollback and observations: 5 minutes.
4. Pilot design, hardware checks and recovery criteria: 15 minutes.
5. Questions: 10 minutes.

Reuse the rehearsed [FOSDEM
video](CFP-FOSDEM-2027.md#demo-video-outline-3-5-min-attach-to-cfp) and its
source evidence. Keep an offline copy and readable screenshots. Tell reviewers
about any special setup. The author of the [demo runbook](CFP-DEMO-SCRIPT.md)
did not execute it end to end. The speaker must capture a real rehearsal before
they promise the demonstration.

This draft omits the earlier abstract's Corral backend, Proxmox API and GPU
claims. A separate Corral/KubeVirt talk would need source verification in that
project, speaker consent and a suitable open call. This proposal does not need
those claims to explain image updates.

## Submission checklist

- [ ] Confirm a speaker's consent, in-person attendance and a travel budget.
- [ ] Confirm the time zone for the deadline, portal limits, duration and selected track.
- [ ] Review both abstracts against the [claim checklist](CONTENT-CLAIM-CHECKLIST.md).
- [ ] Complete the recorded rehearsal with artifact and recovery evidence.
- [ ] Supply the speaker's profile and review agreement and terms for video publication.
- [ ] Submit through an authorized account by November 1; save a public-safe receipt.
- [ ] Record the response, accepted session URL, slides and video in #3179.

Use the [shared ledger
template](CFP-FOSDEM-2027.md#submission-and-response-record) in #3179. The 2–4
week early-submission window has passed as of this research; prioritize a
complete, reviewed submission over adding another abstract. The issue remains
open for submission and acceptance evidence.
