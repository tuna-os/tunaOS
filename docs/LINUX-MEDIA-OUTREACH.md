# Linux publication outreach handoff

Tracks [#3019](https://github.com/tuna-os/tunaos/issues/3019). These are draft pitches
and a press-material checklist for an authorized maintainer. Publication, interview
availability, and contact dates need that person's approval. Keep #3019 open until the
selected pitches have been sent and outcomes recorded.

## Project one-pager

**TunaOS builds Linux desktops as bootable OCI images.** Its factory combines bases with
desktops, kernels, and drivers through a manifest-driven pipeline. The technical story
is how the container build model applies to desktop delivery, updates, and rollback. See
the [architecture guide](AGENT_GUIDE.md), [pipeline](PIPELINE.md), and [build
configuration](../tunaos.toml) for the implementation.

The Enterprise Linux angle is Albacore on AlmaLinux and Yellowfin on AlmaLinux Kitten.
Compare their packages with Fedora, Arch, and Debian within that common pipeline.
Configuration is evidence of design, not proof that every combination is downloadable or
ready for use. Link readers to [tunaos.org](https://tunaos.org) and its current download
instructions only after you check the candidate artifacts.

TunaOS grew from Bluefin LTS; [ADOPTERS.md](../ADOPTERS.md) documents that relationship.
An interview could explore why the project developed a multi-base factory and what it
still shares with upstream. Attribute that history to the maintainer. Do not claim a
unique or first implementation.

**Evidence to supply:** the [adopter ledger](../ADOPTERS.md) distinguishes use by the
maintainer and CI from external adoption. Use the [metrics plan](../ADOPTION-METRICS.md)
to distinguish contributions from discovery, downloads, and installations. Targets do
not establish external use. Dependencies do not establish it either. Cite
consent-confirmed use cases from the ledger and merged contribution links when
available; omit growth figures without a dated source and comparison period.

## Outlet selection and pitch drafts

Each draft needs a named sender and the evidence packet below. Send one relevant angle
per outlet. These are proposals for coverage, not publication commitments. Consult the
official guidance links again on the contact date. LWN needs a human author to write
original copy; its notes below are internal research, not a draft to send.

### LWN: internal research for a human author

**Do not send this agent-generated material to LWN.** The official [author
guide](https://lwn.net/op/AuthorGuide.lwn), checked on October 23, 2026, rejects
machine-generated pitches and articles. An eligible human author must independently
research and write original copy before contact. A human must not approve or edit this
draft and submit it as original copy.

Internal research topics for that author:

- Where shared desktop manifests work across bases and where packages must differ.
- How the factory tests verification, updates, and rollback on one reproducible image.
- Which limitations the test evidence reveals and what a maintainer can demonstrate.

Use the [LWN FAQ](https://lwn.net/op/FAQ.lwn) to check the news-tip route. For a
commissioned contributor article, follow the separate author guide and agree the topic
with LWN before an article. Do not send this generated copy through either route.

### DistroWatch: distribution discovery

Use the existing [submission draft](DISTROWATCH-SUBMISSION.md) and its closed [#1333
tracker](https://github.com/tuna-os/tunaos/issues/1333) for history. Read its closure
and any submission receipts with the maintainer before further contact. A closed
tracker alone does not prove submission or listing. The angle is a
desktop image factory with multiple bases; provide a verified path for installation and
the project's lifecycle policy. Do not describe a draft or submission receipt as a
listing. Record a listing URL only after publication.

### The New Stack / OSS Insider: container workflows for desktops

**Subject:** Story idea: container delivery for Linux desktops

TunaOS builds bootable desktop images through a multi-base OCI pipeline. Would a
technical case study on moving container delivery practices onto desktops fit your
coverage? We propose following a source change through the build pipeline, artifact
verification, and an observed update/rollback on one test machine. The story can examine
where desktop state and hardware make the fleet analogy incomplete. An image build does
not prove enterprise adoption.

Start at [The New Stack](https://thenewstack.io/) and confirm its current route for
editorial submissions before contact. The issue's “OSS Insider” name does not identify a
verified separate recipient: the sender must resolve the intended publication and
official channel before using it. Do not infer an address or send the same message twice
under those names.

### It's FOSS: a practical desktop review

**Subject:** Review idea: trying a bootc desktop from the TunaOS image factory

Would a hands-on look at TunaOS interest your desktop Linux readers? The review could
follow a verified variant from installation to desktop use, then explain image-based
updates and rollback with screenshots from that exact build. We can prepare the artifact
reference, verification instructions, and known limitations for a maintainer to review
before an offer of access. The broader story is how the factory combines bases with
desktops.

Use the official [contact form](https://itsfoss.com/contact-us/) or [project-feature
route](https://itsfoss.com/get-featured-on-its-foss/).

### Linux Handbook: a reproducible administration tutorial

**Subject:** Topic proposal: how to inspect and update a bootable desktop image

Would a tutorial about desktop operations fit your coverage? We would use a verified VM
with TunaOS. It would show how to identify the active deployment and verify an artifact.
A second section would cover an update and rollback after reboot.  The tutorial would
include command output, screenshots, and the limits of what rollback restores. We would
agree the topic before a draft and disclose the author's relationship to TunaOS.

Follow the [author guidelines](https://linuxhandbook.com/write-for-us/), including topic
approval and original-content requirements. Propose a tutorial with technical depth. Do
not send a promotional guest post or copy the It's FOSS pitch.

### Fedora Magazine: a Fedora community engineering story

**Subject:** Topic proposal: lessons from Fedora-based bootc desktops

Could a technical article about TunaOS's Fedora-based Bonito pipeline be useful to
Fedora readers? We propose an article about desktop assembly and bootc validation with
source links, a tested candidate, and lessons useful to other builders. The article
would describe TunaOS as an independent downstream project. It would identify the base
and desktop under test. It would not imply Fedora endorsement or an official edition.

Complete the review in [Fedora outreach readiness](FEDORA-OUTREACH-READINESS.md) first.
Coordinate with the [existing Magazine pitch](FEDORA-MAGAZINE-PITCH.md) owner; check its
historical dates and claims before reuse. Confirm Magazine's current editorial process
before contact.

### AlmaLinux blog: the Enterprise Linux desktop build story

**Subject:** Guest article idea: bootc desktops on AlmaLinux bases

Would a technical guest article about TunaOS's Albacore and Yellowfin build paths fit
the AlmaLinux blog? It could explain the distinction between AlmaLinux and Kitten bases
and how desktop packages enter a bootable image. It would describe the tests for a
desktop recommendation. We would attach source references and one demonstrated
candidate, with support boundaries explicit. This is a downstream community story,
without a claim of AlmaLinux endorsement.

Coordinate with the [AlmaLinux community introduction](ALMALINUX-COMMUNITY-INTRO.md).
For guest articles, use the channel for promotion in the [contribution
guide](https://wiki.almalinux.org/Contribute). Consult the [Promo
SIG](https://wiki.almalinux.org/sigs/Promo.html) for current contact details.

## Evidence and media packet before contact

- [ ] Technical owner selects one variant, desktop, architecture, immutable image
      digest, source commit, and build run. Check [image tags](IMAGE-TAGS.md),
      [green criteria](GREEN-CRITERIA.md), generated [matrix results](MATRIX-STATUS.md),
      and [artifact verification](VERIFY-ARTIFACTS.md). Preserve test dates and
      failures; a successful build alone does not establish installation readiness.
- [ ] Content owner applies the [claim checklist](CONTENT-CLAIM-CHECKLIST.md).
      The older [press kit](PRESSKIT.md) and [tech-press pack](TECH-PRESS-PITCHES.md)
      are background drafts: do not copy their historical version, hardware,
      signature, or readiness claims without current evidence.
- [ ] Use the [screenshot gallery](SCREENSHOTS.md) and
      [installer walkthrough](INSTALLER_SCREENSHOTS.md) as candidate assets.
      Match every selected screenshot to the tested build; attach its variant,
      desktop, architecture, capture date, source run, caption, credit, and reuse
      permission. Refresh stale captures rather than relabelling them current.
- [ ] Capture a short VM demo: boot to desktop, show deployment identity, do an update, and reboot.
      Demonstrate rollback and show the new identity.
      Label cuts and elapsed time; retain the full recording and command output.
      Do not imply that rollback protects user data or that this tests every cell.
- [ ] Confirm the sender, interview availability, download link, known issues,
      and asset permissions before offering interviews, screenshots, or demos.

## Timing and outcome recording

Use the [Q4 promotion calendar](Q4-2026-PROMOTION-CALENDAR.md) as a coordination plan,
not a release announcement. The sender and technical owner should choose an actual
release with a candidate that passes the gates and published release notes. Prepare the
packet before that release; send after verification. If release evidence is missing,
hold the release-specific pitch or use the architecture angle without a promise of a
try-it result.

The [metrics plan](../ADOPTION-METRICS.md) schedules a first snapshot for November 1,
2026. Attach its public URL only after publication. Preserve the measurement period and
methodology. Hacktoberfest participation and merged contributions can provide a separate
community hook. A planned event or metrics launch does not prove adoption. Do not delay
a technical story with evidence to wait for an unsupported growth claim.

Record each approved send in #3019 and link it from the [outreach
ledger](ADOPTION-OUTREACH-STATUS.md). Include outlet, sender, angle, sent date, official
route used, packet/release URL, response, and next action. Keep private addresses and
correspondence out of the public tracker. Follow up once after about two weeks unless
the outlet asks otherwise.

Record no response or a decline explicitly. Coverage needs a published URL; referrals
belong in the monthly metrics snapshot, and adopter claims still need consent.
Cross-link DistroWatch and Fedora work to their existing trackers. Keep one submission
history for each outlet.
