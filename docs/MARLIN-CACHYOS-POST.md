# Marlin on CachyOS — community post draft

> Status: **draft** — for maintainer review. Do **not** post publicly without
> maintainer sign-off (external community action; issue-first per outreach
> policy). Tracking: [#1692](https://github.com/tuna-os/tunaOS/issues/1692).
> Fact-checked 2026-08-14 against README.md, ROADMAP.md, and Containerfile.arch
> in tuna-os/tunaOS (claims below match the repo, no external claims about the
> CachyOS team).

## Purpose

A short community post for r/CachyOS and the CachyOS Discord introducing the
Marlin variant: TunaOS built on an Arch rolling base with CachyOS's
repository/kernel overlay. The post's job is *discovery*, not a stability
claim — Marlin is **Beta** and the overlay kernel path was being hardened all
of the week of 2026-08-10.

## Draft (≈250 words)

**Marlin: an immutable, rollback-safe desktop built on CachyOS's kernel stack**

TunaOS is an image-based desktop distribution: every desktop environment ships
as a bootable OCI container, upgraded atomically with `bootc` — one
transaction, instant `bootc rollback` if anything breaks.

The **Marlin** variant pairs that model with a rolling base: Arch Linux with
the **CachyOS repository overlay**, so `pacman` pulls CachyOS's optimized
packages automatically, and images ship the **linux-cachyos** kernel. Six
desktop flavors (GNOME, KDE Plasma, COSMIC, Niri, XFCE, base) are published
with the CachyOS kernel as `*-cachyos` image flavors.

What that combination gives you: a current, performance-tuned rolling kernel
with the safety net image-based systems are known for — the desktop updates
like a container fleet, not like a `pacman -Syu` roulette wheel.

Honest status: Marlin is **Beta** (x86_64). We spent the week of 2026-08-10
hardening the overlay-kernel path — single kernel-tree initramfs rebuilds
(#1640), removing the stock kernel in favor of a generated initramfs for all
cachyos-overlay kernels (#1641), and accepting built-in boot drivers in the
initramfs parity check (#1679). A cross-variant nvidia-overlay CI regression
is being tracked (#1499); fixes are landing daily.

Want to try it?

```
bootc switch ghcr.io/tuna-os/marlin:gnome-cachyos
```

Then `bootc upgrade` and `bootc rollback` are your update loop. Issues and
ideas welcome in [github.com/tuna-os/tunaOS](https://github.com/tuna-os/tunaOS).

## Fact-check notes (per #1667)

- **True:** Marlin = Arch rolling base + CachyOS repo overlay; `linux-cachyos`
  kernel selected when `[cachyos]` is present in pacman.conf (Containerfile.arch).
- **True:** `*-cachyos` image flavors exist (README build matrix).
- **True:** the cited fixes (#1640, #1641, #1679) were merged the week of 08-10.
- **Honest framing required:** Marlin is Beta; CI matrix showed Marlin 5/16
  red on 2026-08-14 (nvidia-overlay regression #1499, cross-variant). Do not
  call it "stable" or "production-ready."
- **No claims about the CachyOS team/endorsement** — this is TunaOS's use of
  CachyOS's open infrastructure, nothing more.

## Posting checklist

- [ ] Maintainer sign-off (external post — issue-first policy)
- [ ] Re-verify Marlin CI status the day of posting
- [ ] Post to r/CachyOS and CachyOS Discord (community channels, not a sponsor pitch)
- [ ] Cross-link the Marlin ROADMAP row and ADOPTERS.md ecosystem table

---

*Draft prepared by outreach agent (ACMM L6 — full mode). Not for public posting without maintainer sign-off.*
