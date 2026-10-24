# Open Source Summit North America 2027 — CFP Proposal

| Field | Value |
|---|---|
| Status | Draft for maintainer review. Do not submit without maintainer sign-off. |
| Event | Open Source Summit North America 2027, 17–19 May 2027, Vancouver, British Columbia, Canada |
| CFP | Not announced. The Linux Foundation calendar says **Details Coming Soon**. No 2027 deadline or portal is public. |
| Tracking | [#2714](https://github.com/tuna-os/tunaOS/issues/2714) |

The [official event page](https://events.linuxfoundation.org/open-source-summit-north-america/) provides the date and location. The [Linux Foundation calendar](https://events.linuxfoundation.org/about/calendar/) provides the CFP status. The [2026 CFP](https://events.linuxfoundation.org/archive/2026/open-source-summit-north-america/program/cfp/) is a format and topic guide only. It does not set the 2027 tracks, limits, or deadline.

## Submission strategy

Use one talk proposal and one panel proposal. Both proposals use the same project evidence.

1. **Talk:** explain bootc desktops, image management, and the CI delivery pipeline.
2. **Panel:** compare ways to operate desktops as infrastructure. TunaOS shows one implementation.

The 2026 program had talks, panels, and birds-of-a-feather sessions. It listed talks and panels at 30–40 minutes. It listed birds-of-a-feather sessions at 45 minutes to one hour. Use these facts as a guide only.

Confirm the 2027 session types, track names, word limits, speaker policy, and portal after LF posts the CFP. The 2026 CFP used Sessionize. That fact does not set the 2027 portal.

The maintainer owns the submission, speaker commitments, travel decision, and external contact. This draft is not an invitation or a submission.

---

## Talk proposal

### Working title

**The Desktop Is an OCI Image: How bootc Manages a Linux Workstation**

Alternative title: **From bootc Image to Workstation: CI, Rollback, and the Immutable Desktop**.

### Suggested CFP positioning

- **Main subject:** Linux desktop operations
- **Other subjects:** bootc, OCI images, release pipelines, and platform engineering
- **Audience:** Linux administrators, platform engineers, distribution maintainers, desktop developers, and open-source infrastructure teams
- **Format:** 30–40 minute session; prepare a 30-minute cut

These labels are provisional. Use the 2027 track names after LF posts the list.

### Abstract

Server teams now deliver OS changes as artifacts through CI. They build a known input, test it, promote it, observe the result, and keep a rollback path. Many workstations remain special cases. Operators change packages by hand. Teams do not share a contract for delivery. What changes when the desktop is an OCI image?

TunaOS is an open-source image factory for bootc desktop systems. A manifest gives the desktop intent. The pipeline combines that intent with a Linux base and variant layers. Package adapters handle the differences between families of distributions. CI builds the image matrix, runs desktop gates, and writes status from the run results.

The talk follows one change from a manifest to a workstation. It explains the bootc image model, image checks, and the response to a failed matrix cell. It then shows a staged upgrade and a rollback to the prior deployment. The image owns the OS. User data, hardware, and application policy need separate rules.

Attendees get a model for image-based desktops and a delivery checklist. They see the failure modes that matter when a system must be observable and reversible. This is a case study from an open-source project. It does not claim broad adoption by enterprises or serve as a vendor pitch.

### Outline

Use the 40-minute version if the CFP allows it. For a 30-minute slot, use the timed cut below and do not submit both outlines as if they were interchangeable.

1. **The OS artifact — 4 minutes**
   - Why an OCI image fits a workstation
   - Set the boundary: OS state, user data, and hardware configuration
2. **bootc updates and rollbacks — 7 minutes**
   - Image, deployment, staged upgrade, reboot, and rollback
   - What `bootc status` must show before a change is reversible
3. **One image factory across distribution families — 9 minutes**
   - Desktop intent in YAML manifests
   - OS-family package adapters and flavor resolution
   - Use package intent. Do not treat package managers as identical.
4. **CI as the delivery contract — 9 minutes**
   - Dependency-aware build stages and the variant × desktop matrix
   - Build, desktop, parity, and promotion evidence
   - Generated status and the difference between “built” and “green”
5. **Recorded or live workflow — 5 minutes**
   - Inspect the image artifact and digest
   - Stage an upgrade, show both deployments, reboot, and roll back
   - Use a published image only after the submission-day check
6. **Operations lessons — 3 minutes**
   - Rollback is a workflow, not a slogan
   - Hardware and user state have separate rules
   - Docs that another operator can use
7. **Questions — 3 minutes**

For a 30-minute slot: item 1 is 3 minutes, item 2 is 5 minutes, item 3 is 6 minutes, item 4 is 7 minutes, the combined items 5 and 6 are 4 minutes (three minutes of recorded/live demo plus one minute of operations lessons), and questions are 5 minutes. The segments total 30 minutes.

### Demonstration plan

The demo must prove the delivery claims. It must not only show a desktop boot.

1. Inspect a published image. Record its architecture and digest.
2. Show the booted deployment with `bootc status`.
3. Run `sudo bootc upgrade` on a pre-pulled target. Show the new deployment beside the booted one.
4. Reboot. Show the new deployment. Run `sudo bootc rollback`. Reboot. Show the prior digest.
5. Show the matching CI and matrix evidence. Explain the gates that produced it.

Use [the CFP demo script](CFP-DEMO-SCRIPT.md) for the dry run and video rules. Do not claim success until the run produces a real digest and a rollback result. If no image, VM, or CI result exists, use a labelled video. Do not simulate a result.

---

## Panel proposal

### Working title

**Should Teams Operate the Desktop Like Infrastructure?**

### Panel pitch

Many teams still treat desktops as snowflakes. They use declarative tools for servers and containers but not for workstations. An image-based system changes the unit of management. The OS becomes a versioned artifact. The operator can stage an update, roll it back, and use health evidence from the same delivery pipeline.

This panel asks where the model works and where it fails. It asks what a project must prove before an operator calls an update safe. TunaOS shows one case: bootc deployments, manifest assembly, a dependency-aware CI matrix, and status that separates built cells from verified cells. Other panelists should add views from upstream, distribution, fleet, and desktop platform work. No outside person or group has agreed to join.

The panel covers data from users, hardware, rollback, and verification evidence. It also covers the work that maintainers need for a trusted release pipeline. The goal is an operating checklist, not a product comparison. It does not claim that one model fits every desktop.

### Proposed format

| Role | Proposal |
|---|---|
| Length | 30–40 minutes, subject to the 2027 CFP rules |
| Moderator | Maintainer or maintainer-designate |
| TunaOS seat | One maintainer or technical contributor who can explain the image factory and its limits |
| Other seats | Independent voices from bootc/OSTree, distribution or enterprise Linux operations, and desktop platform work |
| Audience | Linux, infrastructure, distribution, and open-source operations teams |

List roles, not names, until a maintainer confirms invitations. The submission must not imply endorsement, partnership, or prior agreement from any outside organization.

### Moderator prompts

1. Which state belongs in the OS image? Which state stays outside it?
2. What evidence can promote an image when the matrix has multiple bases, desktops, architectures, and hardware paths?
3. Does rollback help if user data, firmware, drivers, or services changed at the same time?
4. How should a project report a cell that built but did not meet its checks?
5. What should an operator inspect before the operator adopts a bootc desktop workflow?
6. Which parts of desktop management need local policy instead of a shared image contract?

### Audience takeaways

- A checklist to assess an image-based desktop pipeline.
- The difference between an OCI artifact, a bootc deployment, and a workstation model.
- Questions about test evidence, rollback scope, user state, and project governance.

---

## Speaker and submission coordination

This work needs maintainer identity, availability, or external contact:

- [ ] Choose the talk speaker and moderator before the portal opens.
- [ ] Confirm speaker travel and event terms for Vancouver.
- [ ] Invite panelists after maintainer approval. Store names, affiliations, and consent in the submission record, not this public draft.
- [ ] Ask a technical reviewer to check both drafts against the main branch and matrix status.
- [ ] Dry-run the demo on the record or presentation machine.
- [ ] Check the event page, portal, format, tracks, deadline, and speaker rules before submission.
- [ ] Submit the talk and panel as separate entries if the portal needs them. Link this issue in the maintainer note.
- [ ] After submission, record the URL, format, speaker, and outcome in the outreach record. A draft is not evidence of outreach.

Outreach agents do not submit CFPs, promise attendance, or contact organizers or panelists for the project.

## Claim and evidence guardrails

- Call TunaOS an open-source engineering case study. Do not call it a production enterprise deployment unless `ADOPTERS.md` has consent-confirmed evidence.
- Check image refs, architectures, readiness, and tools with the [content-claim checklist](CONTENT-CLAIM-CHECKLIST.md) before submission.
- Use [matrix status](MATRIX-STATUS.md) for readiness evidence. Do not copy a cell count; it is a time-bound snapshot.
- Use the [agent guide](AGENT_GUIDE.md), [developer guide](DEVELOPER-GUIDE.md), and build config for architecture and pipeline claims. If sources disagree, narrow the claim.
- Treat bootc and distributions as technical context unless a maintainer confirms a relationship. Do not imply endorsement or co-sponsorship.
- Keep panel claims open-source and comparative. Do not list unverified partners, customers, or adoption metrics.

## Reviewer references

- [Official event page](https://events.linuxfoundation.org/open-source-summit-north-america/)
- [LF event calendar](https://events.linuxfoundation.org/about/calendar/)
- [2026 CFP page](https://events.linuxfoundation.org/archive/2026/open-source-summit-north-america/program/cfp/)
- [TunaOS README](../README.md)
- [Agent guide](AGENT_GUIDE.md)
- [Developer guide](DEVELOPER-GUIDE.md)
- [Matrix status](MATRIX-STATUS.md)
- [Artifact verification guide](VERIFY-ARTIFACTS.md)
- [CFP demo script](CFP-DEMO-SCRIPT.md)
- [ADOPTERS.md](../ADOPTERS.md)

---

*Draft prepared for maintainer review under [#2714](https://github.com/tuna-os/tunaOS/issues/2714). Human review and submission are required.*
