# SeaGL 2026 — CFP Draft

> Status: **superseded for 2026 — retained as a reusable community-talk template.**
> **Fact-check correction (2026-08-14, outreach agent):** the original draft's dates and premise were wrong. Verified against [seagl.org](https://seagl.org): SeaGL 14 is **October 23–24, 2026** at the University of Washington HUB (venue change announced 2026-06-01), and the 2026 CFP (opened 2026-04-24, re-opened through **June 30, 2026**) is **closed**. There is no open SeaGL 2026 submission window — see the tracking issue for the corrected plan.
> Tracking issue: [#1691](https://github.com/tuna-os/tunaOS/issues/1691) (SeaGL 2026 CFP — corrected); correction tracked in #1695.
> Next real submission target: **SeaGL 2027** (CFP typically opens ~April 2027).

## Talk title (working)

**Desktop Linux as a Container Fleet: atomic upgrades, instant rollback, and a desktop that updates like servers do**

(Alternative, more enterprise-flavored: *The Immutable Enterprise Desktop* — see [CFP-FOSDEM-2027.md](./CFP-FOSDEM-2027.md) for that variant.)

## Suggested track / format

- **Main track lightning (20 min)** — primary; SeaGL favors short, demo-heavy talks
- **Workshop / birds-of-a-feather** (optional) — hands-on "bootc upgrade + rollback on your own VM"
- SeaGL's audience is Linux power users and FOSS community members (not primarily enterprise IT), so the abstract below leads with the user-facing story and keeps the EL angle as a bonus, not the premise.

## Abstract (≈200 words, submission-ready)

You update your phone and your cloud servers atomically — one transaction, and
roll back if anything breaks. Your desktop is still the odd one out: package
managers that mutate in place, half-broken upgrades, and no safe way back.

TunaOS builds desktop Linux the way modern servers are built: as bootable
containers. Each desktop image — GNOME, KDE Plasma, COSMIC, Niri, or a
lightweight XFCE for old laptops — is an OCI image you pull with `podman`
and boot directly. Upgrades are atomic: the next image is written in the
background, verified, and swapped at reboot; if it misbehaves, `bootc
rollback` puts you back on the last good system in seconds.

This talk demos the full loop live: pull an image, upgrade, break the new
image on purpose, and roll back. We'll also show what this unlocks — the
same image runs on enterprise Linux bases (AlmaLinux 10, CentOS Stream 10),
ARM laptops (Snapdragon X Elite, Apple Silicon work in progress), and a
Kubernetes-native VM manager (Corral) that treats desktops as declarative
resources. No vendor pitch: the whole stack is open source, and every
artifact is signed and reproducible.

Attendees leave with a concrete recipe they can run at home and a clear
comparison to Silverblue, Universal Blue, NixOS, and MicroOS.

## Demo outline (2–3 min, fits a lightning slot)

1. `podman pull` a TunaOS image; show the layered filesystem
2. `bootc upgrade` on a live VM → atomic swap, then intentionally boot a broken image
3. `bootc rollback` → instant return to the last good system
4. (If time) `kubectl apply` a Corral desktop-VM manifest and watch it schedule

## Logistics

- Length: 20 min (lightning) — fits SeaGL's format; a 40-min slot works too
- Speaker: maintainer or maintainer-designate (SeaGL is free to attend; Seattle venue)
- Materials: laptop + pre-built demo VMs (images in GHCR; Corral runs anywhere with KubeVirt)
- SeaGL is volunteer-run and low-budget — no sponsorship ask, just a community talk

## Ecosystem / honesty notes (fact-check discipline, #1667)

- bootc (the foundation) is a CNCF Sandbox project; TunaOS is one of the more
  complete production bootc *desktop* deployments — a credible adoption story
  for the Containers/community crowd without claiming any relationship that
  doesn't exist.
- **No warm-path claims in this abstract.** Per the corrections logged in
  [CFP-FOSDEM-2027.md](./CFP-FOSDEM-2027.md) (2026-08-13), treat castrojo /
  tulilirockz / any external name as cold outreach unless a maintainer
  confirms a current relationship. ADOPTERS.md lists bootc-dev/bootc as an
  upstream dependency only — that is factual, that is all this doc claims.
- Variant/arch claims must match ROADMAP.md at submission time (e.g., Apple
  Silicon is "in progress", not "supported" — see #1684).

## Submission checklist (for SeaGL 2027 / reuse)

- [x] Verify SeaGL dates + CFP window on seagl.org (done 2026-08-14: 2026 event Oct 23–24, 2026 CFP closed 06-30)
- [ ] Re-confirm SeaGL 2027 dates + CFP window (~April 2027)
- [ ] Finalize title + abstract (this draft — adapt to the current ROADMAP state at submission)
- [ ] Record 2–3 min demo video (reuse the #1658 demo outline work)
- [ ] Proof with 1–2 community members (SeaGL reviewers like demos + honest scope)
- [ ] Submit when the portal opens; link the Q3 checkpoint recap (#1610) on acceptance

## Supporting material (for reviewers / talk page)

- Project: [github.com/tuna-os/tunaOS](https://github.com/tuna-os/tunaOS) — 55 stars, 40+ repos, daily image builds
- Blog: [tunaos.org/blog](https://tunaos.org/blog) — 10 posts incl. "The Immutable Desktop Landscape" and "Modern Enterprise Linux Desktops with TunaOS"
- Tech: bootc (CNCF Sandbox), KubeVirt, QEMU, BuildStream
- ADOPTERS: [tuna-os/tunaOS/ADOPTERS.md](https://github.com/tuna-os/tunaOS/blob/main/ADOPTERS.md)

---

*Draft prepared by outreach agent (ACMM L6 — full mode). Review, edit, and submit when the CFP portal opens.*
