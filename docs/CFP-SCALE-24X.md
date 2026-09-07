# SCaLE 24x — CFP Draft

> Status: **draft** — for maintainer review before submission.
> Event: SCaLE 24x, Pasadena, April 1–4, 2027. CFP opened August 1, 2026 and closes November 1, 2026.
> Tracking issue: [#1135](https://github.com/tuna-os/tunaOS/issues/1135) (Q1 2027 CFP season).
> Adapted from [docs/CFP-FOSDEM-2027.md](./CFP-FOSDEM-2027.md) per
> [docs/Q4-2026-PROMOTION-CALENDAR.md](./Q4-2026-PROMOTION-CALENDAR.md)'s
> own plan ("adapt the FOSDEM abstract for SCaLE's format and audience... no
> SCaLE-specific draft exists yet — write one from the FOSDEM abstract
> rather than from scratch") — same underlying talk and project story, not
> a second abstract written independently.

## Why a separate draft, not just the FOSDEM one

SCaLE's audience is broader than FOSDEM's Containers devroom: general
open-source, sysadmin, and platform-engineering attendees, not
container-specialists. FOSDEM's abstract leads with the bootc image model;
this one leads with the more broadly legible "your desktop breaks the same
way your server fleet used to" framing and pulls Corral (the
Kubernetes-native VM angle) forward, since that's the piece platform
engineers in this audience are more likely to already have a mental model
for (declarative infra, GitOps) than bootc/OSTree internals specifically.

## Talk title (working)

**Treating the Desktop Like Infrastructure: Atomic Updates and Kubernetes-Native VMs with TunaOS**

## Suggested track

- **DevOps / Infrastructure-as-Code** (primary)
- **Containers & Virtualization** (secondary)
- **Everything Open / general track** (fallback — SCaLE's broadest track,
  a reasonable landing spot for a project talk that doesn't fit a narrower
  category)

## Abstract (≈230 words, submission-ready)

Most teams have already made peace with treating servers as disposable,
declarative infrastructure — but the desktop is usually the one machine
still managed by hand: manual package upgrades, config drift, and a
"don't touch it, it works" reluctance to update. TunaOS applies the same
image-based model your Kubernetes cluster already uses to the desktop
itself.

We build bootc images — bootable OCI containers — on AlmaLinux 10, CentOS
Stream 10, and Fedora, shipping current desktop environments (GNOME, KDE
Plasma 6, COSMIC, Niri) as atomic, rollback-safe images with the same
manifest-driven, CI-built, signed-artifact pipeline you'd expect for a
production container image, not a desktop ISO.

The second half of the talk is Corral, our Kubernetes-native VM manager:
desktop and service VMs declared as Kubernetes resources, scheduled across
QEMU/KVM locally or a KubeVirt cluster, with snapshots and GPU passthrough
as code. It also speaks a useful subset of the Proxmox VE API on top of
KubeVirt, so existing Proxmox/Terraform/Ansible tooling can drive a
Kubernetes cluster without knowing Corral is there.

Live demos: an atomic desktop update and rollback, and standing up a
declarative desktop VM with Corral. Attendees leave with a working model
of image-based desktops, concrete manifests they can run themselves, and
an honest comparison against Silverblue, uBlue, NixOS, and MicroOS — no
vendor pitch.

## Demo video outline (3–5 min, reuse the FOSDEM recording if timing allows)

Same outline as [docs/CFP-FOSDEM-2027.md](./CFP-FOSDEM-2027.md#demo-video-outline-3-5-min-attach-to-cfp)
— one recording can serve both submissions if the CFP windows overlap
closely enough; re-record only if SCaLE's review process wants a
platform-engineering-first cut (Corral segment leading instead of the
bootc segment).

## Logistics

- Length: SCaLE talks are commonly 45 min including Q&A — expand the
  FOSDEM 30-min outline with more Corral/KubeVirt depth (backend support
  matrix, the Proxmox-API-compat layer) rather than padding the desktop
  half
- Speaker: maintainer or maintainer-designate; SCaLE offers speaker passes
  (confirm current policy when the CFP opens) — budget-friendlier than
  most US conferences but not free like FOSDEM
- Materials: same as FOSDEM — bootc images already in GHCR, Corral runs
  anywhere with KubeVirt or local QEMU

## Submission checklist

- [x] CFP portal opened August 1, 2026
- [ ] Finalize title + abstract (this draft)
- [ ] Decide: reuse the FOSDEM demo video, or re-cut with Corral leading
- [ ] Ask 1–2 community members to proof the abstract for a
      non-container-specialist audience (does the opening land without
      bootc/OSTree background?)
- [ ] Submit to DevOps/Infrastructure-as-Code track first; Containers &
      Virtualization or Everything Open as fallback
- [ ] Submit by November 1, 2026

## Supporting material (for reviewers / talk page)

Same as [docs/CFP-FOSDEM-2027.md](./CFP-FOSDEM-2027.md#supporting-material-for-reviewers--talk-page)
— project repo, blog, ADOPTERS.md, and the Corral repo
([github.com/tuna-os/corral](https://github.com/tuna-os/corral)) specifically,
since this abstract leans on it more than the FOSDEM version does.

---

*Draft prepared by outreach agent. Review, edit, and submit by November 1, 2026.*
