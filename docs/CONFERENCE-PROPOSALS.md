# 2027 conference proposal handoff

Preparation for [#2887](https://github.com/tuna-os/tunaos/issues/2887).
These are drafts, not submissions or speaker commitments. The issue's
2026-10-01 comment references this file, but it was absent from `main` at
293b99d8. The two abstracts below cover the technical angles requested there;
the six-month production-launch story is omitted because a launch timeline
alone does not establish production adoption.

## Event research record — 2026-10-22

This is a dated research record, not a live CFP status dashboard. The issue's
November–December deadline estimates must not be used as organizer deadlines.

- **Open Source Summit North America:** the [official event page](https://events.linuxfoundation.org/open-source-summit-north-america/)
  announces May 17–19, 2027 in Vancouver, outside Q1. It supplies no CFP
  deadline or submission requirements yet. Prefer abstract 1; obtain the
  actual track, duration, word limit and speaker fields when the CFP opens.
- **Flock to Fedora:** the [official Flock wiki](https://fedoraproject.org/wiki/Flock)
  labels 2027 “Coming soon”; no date or deadline is established by that page.
  Prefer abstract 2, emphasizing lessons Fedora contributors can reuse.
  Confirm eligibility, format and portal requirements from the announcement.
- **KubeCon + CloudNativeCon Europe:** the [official CFP](https://events.linuxfoundation.org/kubecon-cloudnativecon-europe/program/cfp/)
  gives March 15–18, 2027 in Barcelona and an October 11, 2026 deadline at
  23:59 CEST (UTC+2). It is already closed. Do not promise a December submission
  for this Q1 event. Abstract 2 can be adapted for a later announced CFP;
  do not assume North America's dates or reuse Europe's requirements.
- **linux.conf.au:** [Linux Australia](https://linux.org.au/) lists both
  linux.conf.au and Everything Open. No 2027 date or CFP was verified from
  that page. Confirm the actual event and an Australia-based willing speaker
  before selecting it; neither a January event nor a September deadline is
  established here.

The existing [FOSDEM](CFP-FOSDEM-2027.md), [SCaLE](CFP-SCALE-24X.md) and
[demo recording script](CFP-DEMO-SCRIPT.md) belong to #1135. Coordinate there
before submitting a duplicate session. Their older claims and dates need
independent verification; they are not evidence for these drafts.

## Abstract 1: Immutable desktops as reviewable infrastructure

Audience: Linux administrators and platform engineers. Proposed format:
40 minutes plus 5 minutes for questions, subject to the selected CFP.

### Submission abstract

A desktop operating system contains more than a package list: it brings a
base distribution, a desktop session, a kernel, drivers, and an update path.
When those choices are assembled by hand, understanding what changed between
two machines becomes an investigation. What would change if the operating
system itself became a reviewable build artifact?

This session examines that question through TunaOS, an open-source image
factory for bootc-based desktop systems. The focus is the engineering model:
how a configuration change travels from a repository to a bootable OCI image,
and what an administrator must still verify before offering that image to
users. It is an architecture walkthrough, with the source files available for
attendees to inspect, rather than a claim of measured enterprise adoption.

We begin with the boundary between build-time composition and runtime state.
A Containerfile can describe the operating-system payload, but it does not
make a user's documents, credentials, or local configuration disposable.
That distinction shapes both an update demonstration and the questions an
operator should ask about recovery. An image rollback is one part of a
recovery plan; the demonstration will keep persistent data and application
state explicit rather than implying that every change is reversed.

Next, we trace one desktop choice through TunaOS's configuration, flavor
resolver, desktop manifest, and Containerfile stages. This shows how an image
factory can make related desktop builds share implementation while retaining
base-specific package handling. We then examine the project's verification
contract: successfully producing an image and proving that a desktop session
works are different checks. Attendees will see where that distinction is
represented in the repository and how it affects the evidence needed for an
adoption recommendation.

The final section turns the walkthrough into a pilot plan. We discuss choosing
a bounded machine population, recording the exact artifact under evaluation,
testing updates and recovery on representative hardware, and collecting user
feedback before expanding scope. The takeaway is a practical review checklist
for evaluating image-based desktops: what is declared, what is built, what is
verified, and what remains the operator's responsibility. Familiarity with
Linux administration is useful; Kubernetes experience is not required.

## Abstract 2: One matrix, many desktops — composing bootc images

Audience: container engineers and distribution contributors. Proposed format:
40 minutes plus 5 minutes for questions, subject to the selected CFP.

### Submission abstract

Container engineers are accustomed to reviewing a build definition and
following it through a pipeline to an artifact. Desktop distributions add
an awkward dimension: the same desktop may need different packages on
different bases, while kernel and driver choices introduce more combinations.
Copying a complete build definition for every combination quickly obscures
which differences are intentional. A matrix makes those choices visible,
but the matrix itself needs an architecture.

This talk uses TunaOS's bootc image factory to explore that architecture.
We follow the source path from the primary configuration through flavor
resolution, desktop manifests, and Containerfile stages. The aim is to show
how to separate a shared desktop installation process from distribution
specific inputs, and how to recognize the places where a shared abstraction
stops being useful. Attendees can apply these lessons to other image factories
without adopting TunaOS or adding a desktop to a Kubernetes cluster.

The first walkthrough follows a single desktop definition. We examine the
manifest's role in package selection and installation, then look at how base
selection determines the build path. The next walkthrough follows an overlay
choice and asks which inputs should be inherited and which should be explicit.
These are source-level examples: the session does not assume that every
possible combination is published, tested, or appropriate for daily use.

We then move from composition to validation. A matrix can describe more
combinations than a project can exercise on real hardware. The talk examines
TunaOS's distinction between build success and desktop readiness, using its
published verification criteria as the discussion framework. We explain why
an expanding matrix needs admission and lifecycle rules, and why generated
status evidence is more useful than a manually maintained list of successful
builds. This is also where contributors can find bounded improvements: a
manifest change, a resolver correction, or a missing verification case.

The session ends with a design exercise: how would you add a new desktop
without copying an entire distribution pipeline? Attendees leave able to
identify the configuration inputs, implementation boundaries, and checks
that such a change needs. Basic familiarity with OCI images and CI is assumed;
bootc internals are introduced through the build path. No fleet-size,
performance, or production-readiness claim is required to explain the model.

## Evidence and slide preparation

Both abstracts describe repository architecture, not adoption metrics. Sources:
[primary configuration](../tunaos.toml),
[flavor resolver](../scripts/resolve-flavor.sh),
[desktop installer](../build_scripts/desktop/install-desktop.sh),
[manifest generator](../scripts/lib/tunaos_packages.py),
[overlay Containerfile](../Containerfile.overlay),
[verification criteria](GREEN-CRITERIA.md), and
[variant lifecycle](../VARIANT-LIFECYCLE.md).
Desktop manifests are generated from primary configuration by the package
configuration code; inspect generated output during rehearsal, not a stale
manifest path in an older guide.
Use the [claim checklist](CONTENT-CLAIM-CHECKLIST.md) before submission.
Do not add star counts, fleet sizes, release maturity, or CNCF affiliation
claims without their own evidence.

Slide outline and speaker notes (timings include transitions):

| Time | Abstract 1 | Abstract 2 |
|---|---|---|
| 0–5 min | Operator problem; define payload versus persistent state | Composition problem; define matrix dimensions |
| 5–15 min | Trace config → manifest → image; show source revision | Trace a desktop through resolver and installer |
| 15–25 min | Recorded update/recovery demo; name tested artifact | Trace overlay inheritance; show base-specific boundaries |
| 25–35 min | Readiness criteria; explain what the demo did not test | Readiness criteria and lifecycle; distinguish untested cells |
| 35–40 min | Bounded pilot checklist | New-desktop design exercise |
| 40–45 min | Questions | Questions |

For abstract 1, record and rehearse the update/recovery segment on a disposable
VM before promising a live demo. Capture artifact digests and before/after
state; keep an offline recording and readable screenshots. The existing
recording script is a starting point, not proof of a successful rehearsal.
For abstract 2, use source excerpts at a named revision; no build on stage is
necessary. Publish the final deck with that revision and any demo limitations.

## Speaker and submission handoff

Potential lead: James Reilly (@hanthor), listed in [MAINTAINERS.md](../MAINTAINERS.md).
This is a candidate, not confirmed availability. A contributor who has actually
worked on manifests, the resolver, or verification could co-present abstract 2;
ask for a volunteer in #2887 rather than inferring willingness from commit history.

The authorized speaker/maintainer needs to:

1. Select two eligible events with open CFPs, confirm attendance/travel and any
   budget, and choose a lead/co-speaker. The closed Europe CFP cannot count
   toward the issue's two-submission goal.
2. Supply a consented bio, affiliation, contact details, location/time zone,
   and previous speaking/video links. Bio template: “[Name] contributes to
   [verified area] in TunaOS. Their work includes [linked contribution].
   This session shares [specific lesson].” Do not invent credentials.
3. Adapt the selected abstract to the portal's word limit, duration, track,
   audience level and required fields; review recording/publication terms and
   code of conduct. Submit through the speaker's own authorized account.
4. Record event, portal URL, exact deadline/time zone, selected abstract,
   speakers, submission receipt/ID and notification date in #2887. Keep
   private contact details and portal credentials out of GitHub.
5. On acceptance, link the final deck, rehearsal result and session page.
   After the event, publish slides/recording links and aggregate attendee
   questions and consented adopter inquiries. Report observations without
   attributing unrelated star changes to the talk.

No proposals have been submitted by this document. Speaker confirmation,
submission receipts, acceptance and post-event reporting remain in #2887.
