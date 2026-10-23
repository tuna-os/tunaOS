# Container ecosystem engagement

Prepared proposals for [#3021](https://github.com/tuna-os/tunaOS/issues/3021).
This pack supports a maintainer's community conversations; it records no sent
messages, partner agreement, or publication. Contact and external outcomes remain
open on the issue.

## Coordinate before contact

Use one conversation per community. Check #3021,
[#2886](https://github.com/tuna-os/tunaOS/issues/2886), and
[the proposal in PR #3711](https://github.com/tuna-os/tunaOS/pull/3711)
before contact. That proposal covers bootc, Universal Blue, Bluefin, and Asahi;
this pack adds Podman and container/developer community proposals. Coordinate the
bootc case study there. Coordinate CNCF
publication with [#1340](https://github.com/tuna-os/tunaOS/issues/1340) and its
[showcase draft](CNCF-BOOTC-SHOWCASE.md). Check claims again before reuse.

The sender first records a proposed channel, tailored ask, follow-up
owner who has agreed to the role, and existing thread (if any) on #3021. A maintainer uses an authorized account to coordinate
official representation and publication. Follow each
community's contribution guidance and agree on placement before the sender posts copy.

## Community routes and proposed asks

Use these official pages to select a suitable channel. Check
current guidance and existing threads at send time.

| Community | Entry point | First useful contribution |
| --- | --- | --- |
| bootc | [Project README and discussion routes](https://github.com/bootc-dev/bootc#community-discussion) | Offer the desktop case study through #2886; ask whether an adopter documentation contribution would help. |
| Podman | [Community page](https://podman.io/community) links discussions, chat, and meetings | Ask for technical review of a bounded rootless developer-workflow demo, then discuss a joint post. |
| Cloud-native / Kubernetes / DevOps / SRE | [CNCF contributor guide](https://contribute.cncf.io/contributors/) links community groups and ambassador resources | Offer a local developer-workstation session to a relevant group; agree on a community spotlight separately from the #1340 editorial pitch. |
| Fedora / RHEL ecosystem | [Fedora bootc community](https://docs.fedoraproject.org/en-US/bootc/community/) | Ask where a desktop image-composition or validation report belongs; keep Fedora and RHEL compatibility claims distinct. |
| CentOS | [SIG directory](https://www.centos.org/sigs/) | Ask which active group would value a CentOS-based desktop validation report; do not assume the issue's “Container SIG” name identifies an active destination. |

### bootc: desktop use cases

> TunaOS builds desktop operating-system images using bootc. We would like to
> contribute a desktop case study with a small composition example and measured
> boot, update, and rollback results. Would “Desktop use cases for bootc” fit your
> documentation or community blog? What review and adopter-listing process should
> we follow?

Use [VISION.md](../VISION.md), [the pipeline](PIPELINE.md), and
[the build configuration](../tunaos.toml) as architecture sources. “Reference
implementation” is a proposal for upstream review, not a status we grant
ourselves. A dependency does not imply endorsement.

### Podman: developer workflow review

> Could we contribute a short “Podman on a TunaOS desktop” walkthrough for review?
> We propose a rootless build/run/edit loop with a small development container.
> We would explain state in the container versus state on the bootc host. If useful, could we adapt the reviewed recipe into a joint tutorial or
> community demo, with your preferred publication and credit process?

The Fedora path in [10-base-packages.sh](../build_scripts/10-base-packages.sh)
explicitly installs Podman. This is source evidence for package intent, not proof
that every published variant contains it or that rootless operation passes.
Do not carry the issue's blanket “ships by default” claim into a post.

Prepare the demo on a verified desktop installation before you offer runnable copy:

1. Select a variant, flavor, architecture, and artifact digest using current
   [matrix evidence](MATRIX-STATUS.md) and [artifact verification](VERIFY-ARTIFACTS.md).
   Record the host deployment and Podman version, and confirm rootless operation
   as an ordinary user. Report missing tools. Do not
   install host packages to make a “preinstalled” claim pass.
2. Choose a small example application and identify its container
   base. Record its digest and the application source revision. Build and run it
   rootlessly, edit the source, rebuild, and demonstrate the changed output.
3. Demonstrate a workspace mount with applicable permissions and SELinux
   labels. Document the exact command and observed result on that cell. Keep
   test data disposable and explain cleanup of the demo's own containers/images.
4. Explain updates to the host image separately from updates to application containers.
   Include measured bootc update/rollback results only after a demonstration. Do not
   promise recovery of workspace or container-volume data through host rollback.
5. Attach the transcript and limitations to #3021 for a technical reviewer.
   Publish runnable instructions only after this rehearsal passes. The author has
   not run this demo.

### Cloud-native: immutable desktops for development

> Would your community be interested in a technical session about an
> image-based desktop for infrastructure development? We can pair a bootc host
> lifecycle explanation with a reviewed workflow for rootless Podman. We would explain
> which data persists. Which practical question would
> make this useful for your DevOps, SRE, or Kubernetes contributors?

Proposed outline for “Immutable desktops for cloud-native development”: compare
the host lifecycle with the application lifecycle. Walk through the measured Podman example,
then discuss reproducibility and failure observations. Kubernetes cluster tools
are optional additions that need explicit setup and independent verification;
this proposal does not claim that TunaOS ships or validates them.

CNCF's [ambassador resources](https://contribute.cncf.io/contributors/) are for
individuals in the community. An interested person can assess that program
under its current rules; TunaOS cannot apply as an organizational ambassador or
promise someone else's participation. A community-group session or editorial
spotlight is a separate request and does not confer CNCF endorsement.

### Fedora, RHEL, and CentOS: share a technical report

> We would like to share a reproducible desktop composition/validation report
> from a TunaOS image using a related base. Could you point us to the appropriate
> public discussion and a useful test question? We can contribute logs, upstream
> version details, and a small reproducer.

Name the actual base from the build configuration and follow that community's
process for reports. A Fedora result is not a RHEL result. Route upstream defects
with a minimal reproducer; keep TunaOS composition problems in TunaOS. After review, ask the
group whether cross-links between documents would help.

## Follow-up and completion evidence

Use dated comments on the issue as receipts. Each contact record contains the community/thread URL, sender and
follow-up owner, exact ask, response or no-response, next action, and agreed
follow-up date. Do not publish private correspondence or names without consent.
If there is no response, record that outcome. Then decide if a
follow-up in the same thread is appropriate. Respect declines.

Before publication, run the [content claim checklist](CONTENT-CLAIM-CHECKLIST.md),
get technical review, and agree on partner credits and placement. Link the
published content and partner acknowledgement back to #3021 and the related
tracker. A prepared draft or sent pitch is not an accepted collaboration.

This PR prepares the tailored asks and demo review criteria; it does not
complete #3021. Keep the PR description linked with `Refs #3021`.

#3021 stays open until receipts of contact
cover bootc and Podman. Record a response to the joint content proposal.
Document the outcome of the CNCF/community spotlight or ambassador exploration
(including a decline). Record which Fedora/CentOS group responds too. Do not
invent a partnership to close the tracker.
