# FOSDEM 2027 — CFP Draft

> Status: **speaker package prepared; talk CFP not open yet** — for maintainer
> review before submission.
> Event: FOSDEM 2027, Brussels, **30–31 January 2027**
> ([official announcement](https://fosdem.org/2027/news/fosdem-2027-dates/)).
> Tracking issue: [#2838](https://github.com/tuna-os/tunaOS/issues/2838).

## Talk title (working)

**The Immutable Enterprise Desktop: bootc, Corral, and the case for cloud-native desktops**

## Candidate track / devroom

Do not select a room until FOSDEM publishes the accepted devrooms on
**20 October**. The current call is for devroom organizers, not for individual
talks. FOSDEM expects the talk calls to open around **27 October**. Follow the
[official devroom timeline](https://fosdem.org/2027/news/call-for-devrooms/)
and choose a room from the published list.

If accepted for 2027, these themes are the best fits:

- **Containers** — bootc/OSTree-based image model
- **Desktops** — desktop UX angle
- **Virtualization / infrastructure** — Corral + KubeVirt

The speaker must submit through the selected room's talk CFP. Do **not** use
the current devroom-organizer form for this proposal.

## Abstract (≈250 words, submission-ready)

Enterprise Linux runs the world's servers but has never had a good answer
for the desktop. RHEL, AlmaLinux and CentOS Stream ship desktops that track
decade-old package sets, so most EL shops run something different on the
desk — two package ecosystems, two update cadences, and a permanent
server/desktop split.

TunaOS closes that gap with the technology that already runs the datacenter:
bootable containers. We build bootc images on AlmaLinux 10, CentOS Stream 10
and Fedora, then ship current desktop environments — GNOME backported to the
EL base, KDE Plasma 6, the Rust-built COSMIC, the scrollable-tiling Niri —
as atomic, rollback-safe images. The desktop updates like a container fleet:
one transaction, rollback on failure, verified upgrades.

This talk walks through the full stack. We cover the bootc image model and
how EL bases make it enterprise-credible (10-year lifecycles, existing
compliance and patch processes). We show the manifest-driven build pipeline
that turns a YAML file into a published, multi-arch desktop image. And we
demonstrate Corral, our Kubernetes-native VM manager, which treats desktop
VMs as declarative resources — bringing the desktop into the same estate as
the cluster, with schedules, snapshots, and GPU passthrough as code.

Attendees leave with a working mental model of image-based desktops on EL,
concrete YAML/podman recipes they can run, and an honest comparison of where
this fits versus Silverblue, uBlue, NixOS, and MicroOS. No vendor pitch —
this is an open-source project's architecture talk with live demos.

## Demo video outline (3–5 min, link from the CFP if permitted)

The beats, in order:

1. `podman` pull of a TunaOS image; show the layered FS
2. `bootc upgrade` on a live VM → atomic swap + `bootc rollback` on failure
3. Corral: declare a desktop VM as a manifest, `kubectl apply`, watch it schedule
4. Boot the updated image; GNOME session running on AlmaLinux 10

**To record it, use [CFP-DEMO-SCRIPT.md](./CFP-DEMO-SCRIPT.md)** — the
shot list with the real commands (`just qcow2`, `scripts/run-vm.sh demo`,
`just corral-build`), per-shot timings, what each shot has to prove to a
reviewer, and the pre-pull step without which `bootc upgrade` does not fit in
five minutes. The same recording is reused for SCaLE 24x instead of shot
twice.

## Logistics

- Length: request 30 min (25 + Q&A) if the selected devroom offers that format.
  Copy its published duration into the final submission.
- Speaker: maintainer or maintainer-designate. FOSDEM asks each speaker to
  submit their proposal. The primary speaker must confirm their account,
  availability, and travel plan before submission.
- Backup speaker: name one person who can deliver the same session. Confirm
  their Brussels availability before the deadline.
- Attendance is free and needs no registration. Speakers pay for travel and
  hotels.
- Materials: laptop + demo VMs pre-built (bootc images exist in GHCR; Corral runs anywhere with KubeVirt)

## bootc / CNCF ecosystem angle (#1340)

bootc is a CNCF Sandbox project, and TunaOS is one of the more complete
production bootc *desktop* deployments (37 published editions, daily GNOME
releases, keyless-signed artifacts) — a concrete adoption story for a
sandbox project working toward incubation.

**Correction (2026-08-13):** an earlier version of this section claimed
Jorge Castro (castrojo, CNCF Developer Relations and a Universal Blue
founder)'s "201-commit contributor and CODEOWNERS entry" status meant this
wasn't cold outreach. That doesn't hold up — re-verified via the GitHub
API: every one of castrojo's 201 commits predates `tuna-os/tunaOS`'s own
creation (2025-07-30), the latest is 2025-05-28, and a search across this
repo's issues/PRs turns up zero comments, authored issues, or reviews from
castrojo, ever. Same pattern as the retracted shimonenator claim (#1317)
and the tulilirockz "warm path" correction (#1339): the commits are
inherited pre-fork history from bluefin-lts, not real engagement with this
repo. `.github/CODEOWNERS` still lists castrojo (and tulilirockz), but
given both show zero real post-fork activity, that file itself looks like
it was carried over unchanged from the fork instead of reflecting actual
current maintainers — worth a maintainer's separate look, not assumed here.

Treat this as cold outreach unless a maintainer confirms an actual current
relationship.

This makes the FOSDEM talk (Containers devroom) a natural fit for a
CNCF-adjacent bootc ecosystem showcase, not just a standalone project talk.
**A pitch to bootc-dev / CNCF channels has not been sent** — that's a
maintainer decision (it's an external, public action on the org's behalf),
not something to originate from this doc. If a maintainer wants to make
that pitch, this CFP abstract and the ADOPTERS.md ecosystem table (which
already lists bootc-dev/bootc as an upstream dependency) are the supporting
material to point to.

## Official timeline and submission checklist

The [FOSDEM 2027 devroom call](https://fosdem.org/2027/news/call-for-devrooms/)
publishes the dates that constrain this talk proposal:

- **4 October 2026:** devroom-organizer proposals close
- **20 October 2026:** accepted devrooms announced
- **Around 27 October 2026:** devrooms issue their talk Calls for Participation
- **7 December 2026 or earlier:** complete devroom schedules are due
- **30–31 January 2027:** FOSDEM 2027

Before the talk CFP opens:

- [x] Verify event dates and the official participation timeline
- [ ] Maintainer approves the title and abstract
- [ ] Name a primary speaker and backup; both confirm availability and travel
- [ ] Record the 3–5 minute demo — follow
      [CFP-DEMO-SCRIPT.md](./CFP-DEMO-SCRIPT.md); its "Before you record" table
      is the concrete version of "needs a spare laptop/VM"
- [ ] Ask 1–2 community members to proof the abstract

After FOSDEM announces the accepted devrooms:

- [ ] Select the best-fit accepted room; do not assume a Containers or Desktops
      room exists until it appears in the 2027 list
- [ ] Copy that room's exact deadline, duration, required fields, and submission
      URL into this document
- [ ] Let the named speaker submit the proposal; FOSDEM asks speakers to do this
- [ ] Record the submission date and public proposal URL in
      [ADOPTION-OUTREACH-STATUS.md](./ADOPTION-OUTREACH-STATUS.md)
- [ ] Record acceptance or rejection in the same ledger and in #2838
- [ ] (Optional, maintainer call) Pitch a bootc-ecosystem case-study feature to
      bootc-dev/CNCF channels — see #1340

## Supporting material (for reviewers / talk page)

- Project: [github.com/tuna-os/tunaOS](https://github.com/tuna-os/tunaOS) — 55 stars, 37 active repos
  in the org, daily image builds *(counts as of 2026-08-14; re-check before submitting — the
  previous figures were undated and had already drifted)*
- Blog: [tunaos.org/blog](https://tunaos.org/blog) — 10 posts incl. "The Immutable Desktop Landscape" and "Modern Enterprise Linux Desktops with TunaOS"
- Tech: bootc (CNCF Sandbox), KubeVirt, QEMU, BuildStream
- ADOPTERS: [tuna-os/tunaOS/ADOPTERS.md](https://github.com/tuna-os/tunaOS/blob/main/ADOPTERS.md)

---

*Draft prepared by outreach agent (ACMM L6 — full mode). Official dates and
participation sequence verified against fosdem.org on 2026-10-03; review, edit,
and submit when the selected devroom's talk CFP opens.*
