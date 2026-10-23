# AlmaLinux community collaboration proposal

> Draft for maintainer review; no external message or submission recorded here.
> Tracks [#3016](https://github.com/tuna-os/tunaos/issues/3016), as a follow-up to
> [#1757](https://github.com/tuna-os/tunaos/issues/1757).

## Purpose and evidence

Prepare an Atomic SIG conversation, a joint blog proposal, a conference pitch, and a
case study with evaluator consent. An authorized representative of TunaOS sends the
messages and follows up, as required by [AGENT_GUIDE.md](../AGENT_GUIDE.md). Assign that
person in #3016 before you send; do not imply that AlmaLinux has agreed to a partnership
or that an organization already uses TunaOS.

The base inputs are explicit in [tunaos.toml](../../tunaos.toml):
`variants.albacore.base_image` uses AlmaLinux bootc `10`, and
`variants.yellowfin.base_image` uses AlmaLinux bootc `10-kitten`. These are build
configuration facts, not evidence that a particular image is ready for enterprise
deployment. Apply the [content claim checklist](../CONTENT-CLAIM-CHECKLIST.md) before
you send any draft. Use [GREEN-CRITERIA.md](../GREEN-CRITERIA.md) and the generated
[MATRIX-STATUS.md](../MATRIX-STATUS.md) for readiness evidence; include an exact image
digest and dated test results in any demonstration or article.

The old playbook described a gap in desktop projects and proposed a monthly SIG
presentation. The [Atomic SIG's own page](https://wiki.almalinux.org/sigs/Atomic.html)
lists projects for desktops and asynchronous work without regular meetings. Frame the
proposal as an exchange between desktop projects, and ask whether a presentation would
be useful. Verify rollback, signatures, release cadence, and support for the chosen
image before you make claims.

## Contact routes

Use the official pages to find current recipients. Routes checked on 2026-10-23; follow
their current instructions when you send.

| Purpose | Official route | First request |
|---|---|---|
| Technical exchange and cross-promotion | [Atomic SIG](https://wiki.almalinux.org/sigs/Atomic.html), via its linked Mattermost channel and listed leads | Ask the leads who can review a short downstream desktop comparison and whether a shared testing topic is useful. |
| Guest blog and editorial coordination | [Contribution guide](https://wiki.almalinux.org/Contribute), via its Marketing channel | Ask for an editor, preferred format, and whether a jointly reviewed guest article fits. |
| Speaking opportunities | [AlmaLinux Events](https://events.almalinux.org/), which identifies the Marketing SIG as its contact | Ask which Q4 2026 / Q1 2027 event or community session accepts proposals, and obtain its actual CFP URL and deadline. |

Do not treat `lists.almalinux.org` as a Discourse URL. For general introductions, use
the forum/chat links in the contribution guide. The older [community
introduction](../ALMALINUX-COMMUNITY-INTRO.md) remains background; use the narrower,
evidence-based copy below for this proposal.

## Atomic SIG first-contact draft

**Subject:** TunaOS / Atomic SIG: exchange on AlmaLinux-based desktop evaluation

Hello to the Atomic SIG,

TunaOS builds desktop images with Albacore configured on AlmaLinux 10 bootc and
Yellowfin on AlmaLinux Kitten 10 bootc. We would like to exchange lessons with your
Atomic Desktop and Workstation contributors, with a focus on image updates, desktop
verification, and reproducible failure reports.

Would a short comparison of build inputs and test methods be useful? We can bring our
[EL10 Containerfile](../../Containerfile.el10), [desktop
manifests](../../manifests/desktops/), and [verification
criteria](../GREEN-CRITERIA.md), then agree on one small topic for shared tests. We
would also welcome your review of a community blog outline. If useful after technical
review, could we link to each other's relevant documentation? Any cross-promotion would
use text that both projects approve.

Who should coordinate this conversation, and would you prefer an asynchronous thread or
a short demo? Our tracker is
[tuna-os/tunaos#3016](https://github.com/tuna-os/tunaos/issues/3016).

## Joint blog / documentation pitch

**Proposed title:** Modern desktops for Enterprise Linux with TunaOS

**Draft to the `Marketing` channel:** We would like to propose an educational guest
article about how to evaluate desktops from TunaOS on AlmaLinux. The article would
distinguish upstream work from downstream choices and link to projects from the Atomic
SIG. It would describe a reproducible evaluation with explicit limits. Could an editor
review the outline below with a contributor from the Atomic SIG? We can adapt it to your
format and co-author it if a contributor wishes; we do not assume a co-author or
publication.

Proposed outline:

1. Why evaluate an image-based desktop: an administrator's update and recovery
   questions, and the distinction between Albacore and Yellowfin base inputs.
2. Architecture: AlmaLinux bootc inputs, TunaOS desktop manifests, and the
   relationship to the SIG's own Desktop and Workstation projects.
3. A bounded evaluation: one variant, desktop, architecture, image digest,
   disposable VM, and dated install/update/recovery observations. Link to
   [artifact verification](../VERIFY-ARTIFACTS.md) and the canonical
   [user documentation](https://tunaos.org); reproduce instructions before publication.
4. Limitations: report failures and untested behavior; explain which workloads,
   hardware, and fleet-management questions remain unevaluated. Rollback does
   not replace backups or guarantee recovery of application data.
5. Invitation: contribute a reproducible test or volunteer for the evaluation
   interview below, with no claim that upstream dependencies are adopters.

After editorial interest, the TunaOS sender supplies a tested evidence bundle, records
reviewer feedback in #3016, and follows the upstream [instructions for blog
contributions](https://github.com/AlmaLinux/almalinux.org#contributing---blog-posts).
Both projects approve attribution and final copy before publication.

## Speaking proposal: Q4 2026 / Q1 2027 exploration

**Title:** Evaluate an AlmaLinux-based desktop with bootc

**Abstract:** How can an administrator evaluate an image-based desktop and distinguish a
successful build from a usable workstation? This session walks through TunaOS's
AlmaLinux-based build inputs, desktop manifests, and verification criteria. A demo in a
disposable VM follows an image through installation, an update, and recovery. We report
test results and unknowns. We invite contributors from the Atomic SIG to compare test
methods and identify reusable checks across projects.

**Format:** propose a 10-minute talk; offer a 25-minute technical session if organizers
prefer. Audience: desktop evaluators, EL administrators, and bootc contributors. An
authorized speaker supplies their own biography, availability, and any travel budget
approval before submission.

The example event in #3016 is AlmaLinux Connect. No organizer has confirmed a session.
Ask `Marketing` for the appropriate event and verify its date, CFP deadline, format, and
policy for video capture on the official event page. If no CFP accepts a relevant
proposal, ask whether an asynchronous demo is welcome; do not invent a deadline or
assume a regular community call.

Demo outline: two minutes on base inputs and three on build/test criteria. Allow three
for install/update/recovery evidence and two for limitations and Q&A. Use
[CFP-DEMO-SCRIPT.md](../CFP-DEMO-SCRIPT.md) as a model. Rehearse on the exact image
digest and retain a video with logs if a live demo fails.

## Joint evaluation case-study invitation

**Draft invitation:** Does your organization plan to evaluate an AlmaLinux-based
workstation? We seek a volunteer to document a bounded pilot of TunaOS. Describe the
workload, image, hardware or VM, installation, updates, recovery, application
compatibility, and unresolved problems. Taking part does not imply an endorsement or a
commitment to deploy. You choose whether we may publish your organization's name,
quotes, and results. You review the proposed text before publication.

Use the workflow for consent in the [adoption call](../ADOPTION-CALL.md). Agree on the
pilot scope and stop conditions with the evaluator before tests; use a disposable
environment or backed-up test machine. Record:

- Environment, variant, desktop, architecture, digest, and evaluation dates.
- Workload and baseline; observed install/update/recovery outcomes with logs,
  elapsed times where measured, failures, and workarounds.
- Evaluator's deployment decision, remaining blockers, and support expectations.
- Explicit permission for names, quotes, screenshots, and publication venue;
  redact identifiers and private logs before you share them.

An invitation or pilot is not a production adopter. Only add an entry to
[ADOPTERS.md](../../ADOPTERS.md) with consent-confirmed evidence and the correct
production or evaluation classification. Publish negative findings as agreed with the
participant; do not fabricate a joint success story.

## Handoff and follow-up

1. In #3016, name the authorized sender, approve the message text, and choose
   the initial channel. Refresh the technical evidence before you send.
2. Send an initial message to the SIG. Record the date, recipient/channel, and thread URL in #3016 and the
   [outreach ledger](../ADOPTION-OUTREACH-STATUS.md). Record replies and agreed
   actions; an accepted invitation is not a partnership agreement.
3. After interest, send the blog outline to `Marketing` and the talk proposal
   to the actual event contact. Record editorial review, CFP receipt, and
   publication or presentation URLs separately.
4. If unanswered after two weeks, send one polite follow-up in the original
   thread. If still unanswered after another two weeks, record no response
   and stop contact unless they invite you back. Respect a decline immediately.
5. Record each evaluation with consent separately. Report actual responses,
   reviewed materials, submissions, and completed pilots; do not use image
   pulls or upstream dependencies as adoption evidence.

The repository deliverable is this proposal pack. External contact, publication, CFP
submission, and any case study remain open under #3016 until the sender records evidence
of those actions.