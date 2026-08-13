# FOSDEM 2027 — CFP Draft

> Status: **draft** — for maintainer review before submission.
> Event: FOSDEM 2027, Brussels, 6–7 Feb 2027. CFP typically opens ~October 2026.
> Tracking issue: [#1135](https://github.com/tuna-os/tunaOS/issues/1135) (Q1 2027 CFP season).

## Talk title (working)

**The Immutable Enterprise Desktop: bootc, Corral, and the case for cloud-native desktops**

## Suggested track / devroom

- **Containers devroom** (primary) — bootc/OSTree-based image model
- **Desktops devroom** (secondary) — desktop UX angle
- **Virtualization / infrastructure** (fallback) — Corral + KubeVirt

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

## Demo video outline (3–5 min, attach to CFP)

1. `podman` pull of a TunaOS image; show the layered FS
2. `bootc upgrade` on a live VM → atomic swap + `bootc rollback` on failure
3. Corral: declare a desktop VM as a manifest, `kubectl apply`, watch it schedule
4. Boot the updated image; GNOME session running on AlmaLinux 10

## Logistics

- Length: 30 min (25 + Q&A) — fits FOSDEM devroom format
- Speaker: maintainer or maintainer-designate (travel: FOSDEM is free to attend; Brussels transit from most of Europe)
- Materials: laptop + demo VMs pre-built (bootc images exist in GHCR; Corral runs anywhere with KubeVirt)

## bootc / CNCF ecosystem angle (#1340)

bootc is a CNCF Sandbox project, and TunaOS is one of the more complete
production bootc *desktop* deployments (37 published editions, daily GNOME
releases, keyless-signed artifacts) — a concrete adoption story for a
sandbox project working toward incubation. This isn't cold outreach: Jorge
Castro (castrojo), CNCF Developer Relations and a Universal Blue founder, is
already a 201-commit contributor and CODEOWNERS entry on this repo
(verified via the GitHub API and `.github/CODEOWNERS`, 2026-08-13).

This makes the FOSDEM talk (Containers devroom) a natural fit for a
CNCF-adjacent bootc ecosystem showcase, not just a standalone project talk.
**A pitch to bootc-dev / CNCF channels has not been sent** — that's a
maintainer decision (it's an external, public action on the org's behalf),
not something to originate from this doc. If a maintainer wants to make
that pitch, this CFP abstract and the ADOPTERS.md ecosystem table (which
already lists bootc-dev/bootc as an upstream dependency) are the supporting
material to point to.

## Submission checklist

- [ ] CFP portal opens (~Oct 2026) — confirm exact date
- [ ] Finalize title + abstract (this draft)
- [ ] Record demo video (3–5 min) — needs a spare laptop/VM
- [ ] Ask 1–2 community members to proof the abstract (FOSDEM reviewers like demos + no-vendor-pitch)
- [ ] Submit to Containers devroom first; fall back to Desktops if categories allow
- [ ] (Optional, maintainer call) Pitch a bootc-ecosystem case-study feature to bootc-dev/CNCF channels — see #1340

## Supporting material (for reviewers / talk page)

- Project: [github.com/tuna-os/tunaOS](https://github.com/tuna-os/tunaOS) — 56 stars, 40+ repos, daily image builds
- Blog: [tunaos.org/blog](https://tunaos.org/blog) — 10 posts incl. "The Immutable Desktop Landscape" and "Modern Enterprise Linux Desktops with TunaOS"
- Tech: bootc (CNCF Sandbox), KubeVirt, QEMU, BuildStream
- ADOPTERS: [tuna-os/tunaOS/ADOPTERS.md](https://github.com/tuna-os/tunaOS/blob/main/ADOPTERS.md)

---

*Draft prepared by outreach agent (ACMM L6 — full mode). Review, edit, and submit when the CFP portal opens.*
