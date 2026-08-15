# TunaOS on AlmaLinux — community post draft

> Status: **draft** — for maintainer review. Do **not** post publicly without
> maintainer sign-off (external community action; issue-first per outreach
> policy). Tracking: [#1757](https://github.com/tuna-os/tunaOS/issues/1757).
> Fact-checked 2026-08-15 against README.md and the variant table in
> tuna-os/tunaOS (claims below match the repo; no claims about the AlmaLinux
> team or endorsement).

## Purpose

A community post for the AlmaLinux Discourse (lists.almalinux.org) and the
AlmaLinux Atomic SIG channel introducing TunaOS as an immutable, bootc-based
desktop built on AlmaLinux. TunaOS ships **two** AlmaLinux-based variants
(Albacore on AlmaLinux 10 / RHEL 10, Yellowfin on AlmaLinux Kitten 10) yet the
AlmaLinux community has seen none of the release-notes traffic that goes to
Fedora-centric channels. The post's job is *discovery* — introduce an
EL10-native immutable desktop use case to the community that maintains the base
OS it builds on.

## Draft (≈260 words)

**TunaOS: an immutable desktop on AlmaLinux 10**

TunaOS is an image-based desktop distribution: each desktop environment ships
as a bootable OCI container, upgraded atomically with `bootc` — one
transaction, instant `bootc rollback` if anything breaks. Two of its flagship
variants are built directly on AlmaLinux:

- **Albacore** — AlmaLinux 10 (RHEL 10), GNOME/KDE/COSMIC/Niri flavors, x86_64
  and arm64
- **Yellowfin** — AlmaLinux Kitten 10, GNOME/KDE/COSMIC/Niri flavors, x86_64
  and arm64

What that combination gives you: a stable, enterprise-grade EL10 base with the
safety net image-based systems are known for — the desktop updates like a
container fleet, not like a `dnf update` roulette wheel. Base images are
rebuilt daily, releases are signed with keyless Sigstore signatures, and the
project publishes verified boot reports for each image.

Honest status: the AlmaLinux variants are the mature line (daily releases since
spring 2026), while newer Fedora/Arch/Ubuntu variants are at various stages of
stability. TunaOS is a small project — the maintainer plus a growing pool of
first-time contributors — and its roadmap themes for Q3 2026 are "Expand"
(flavor/variant coverage) and Q4 "Mature" (adoption evidence). It also keeps a
working relationship with the AlmaLinux **Atomic SIG** chat — bootc-based
systems are the SIG's exact remit.

Want to try it?

```
bootc switch ghcr.io/tuna-os/albacore:gnome
```

Then `bootc upgrade` and `bootc rollback` are your update loop. Issues and
ideas welcome in [github.com/tuna-os/tunaOS](https://github.com/tuna-os/tunaOS).

## Fact-check notes

- Variant → base mapping verified against README.md variant table (Albacore =
  AlmaLinux 10/RHEL 10; Yellowfin = AlmaLinux Kitten 10), 08-15.
- "Daily releases since spring 2026" — verify Release API state on posting day;
  the gnome flavor has published daily through 08-15.
- Keyless Sigstore signing — matches repo cosign.pub + merged keyless-signing
  milestone (#1187); re-verify on posting day.
- **No claims about the AlmaLinux team/endorsement** — this is TunaOS's use of
  AlmaLinux's open infrastructure, nothing more. ADOPTERS.md lists AlmaLinux
  only as an upstream dependency, not an adopter (08-15 check).

## Posting checklist

- [ ] Maintainer sign-off (external post — issue-first policy)
- [ ] Re-verify release-cadence claim the day of posting
- [ ] Post to AlmaLinux Discourse (lists.almalinux.org) + share the link in the
      Atomic SIG channel (chat.almalinux.org/almalinux/channels/sigatomic)
- [ ] Cross-link the Albacore/Yellowfin ROADMAP rows and the ADOPTERS.md
      ecosystem table
- [ ] Record the thread URL in ADOPTION-OUTREACH-STATUS.md per the update rules

---

*Draft prepared by outreach agent (ACMM L6 — full mode). Not for public posting without maintainer sign-off.*
