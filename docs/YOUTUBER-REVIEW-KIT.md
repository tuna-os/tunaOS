# Linux YouTuber Review Kit

> Status: **draft** — for maintainer review. Contact with creators is a
> maintainer action; this agent does not reach out to external parties.
> Tracking issue: [#1535](https://github.com/tuna-os/tunaOS/issues/1535).
> Prepared: 2026-08-14.

## Target creators (ranked by fit)

Prioritized by existing bootc/atomic-desktop coverage history (the same
criteria the issue proposed):

1. **DistroTube** — has covered Bluefin (TunaOS's upstream lineage)
2. **Chris Titus Tech** — has covered Fedora Atomic / immutable desktops
3. **The Linux Experiment** — broad distro coverage, good general-audience fit
4. **Michael Horn** — ARM-focused; hold for a second wave once the ARM story
   (see below) has a complete download

## What's ready to send today

The x86 download checks date to 2026-08-14. Re-check each link before use.
The 2026-10-17 [X13s assessment](X13S-SUPPORT.md) corrects the earlier ARM ISO claims.

| Story | Variant | Download | Notes |
|---|---|---|---|
| Enterprise Linux desktop, stable | Yellowfin GNOME | [yellowfin-gnome-latest.iso](https://download.tunaos.org/live-isos/yellowfin-gnome-latest.iso) | The flagship, most-tested variant |
| Fedora desktop | Bonito GNOME | [bonito-gnome-latest.iso](https://download.tunaos.org/live-isos/bonito-gnome-latest.iso) | Bonito is still Beta (GA tracked in #272) — say so if it comes up |
| ThinkPad X13s / Snapdragon 8cx Gen3 (SC8280XP), not X Elite | Proposed `bonito:gnome-x13s`; no implementation | [Assessment](X13S-SUPPORT.md), not an ISO | Read-only observations of postmarketOS. No TunaOS boot or install test. |

**Before sending any link**, re-check `https://tunaos.org/download` (or
re-`curl -I` the URL) — these are `-latest.iso` convenience pointers, not
pinned artifacts, and their freshness depends on which publish pipeline last
touched them.

## Known gap: Gurnard has no downloadable ISO yet

The issue this kit answers assumed a ready "Gurnard pantheon" ISO to send
alongside the others. Checked live against `tunaos.org/iso-index.json`
(189 total published artifacts, all 8 categories) and directly against
`download.tunaos.org`: **zero Gurnard entries exist anywhere.**

Root cause, confirmed in `.github/build-config.yml`: Gurnard's `pantheon`
flavor has `build_image: true` but no `build_iso: true` — the pipeline never
builds a live ISO for it, only the container image. This matches Gurnard's
status in [ROADMAP.md](../ROADMAP.md): **Experimental**, predating the
variant admission gate (#1196), pending the 2026-08-22 Q3 checkpoint
decision (#1341).

Also checked: the issue's proposed "Bonito niri" doesn't exist as a
published ISO either — only `bonito-gnome` and `bonito-gnome-nvidia` are
live; niri isn't in Bonito's published-ISO set today.

**Recommendation**: don't include Gurnard in the first wave. Sending a
reviewer a 404 (or asking them to build their own ISO from source) on a
project's *first* pitch to a channel with 100k+ subscribers is worse than
not pitching the Gurnard story yet. Lead with Yellowfin/Bonito (stable,
verified x86 downloads). Hold the X13s pitch until boot and install qualification ends.
ARM64 OCI publication does not validate hardware. Revisit Gurnard once
`build_iso: true` lands for it and a real download exists — worth its own
follow-up issue if a maintainer wants to prioritize that ahead of the
09-01 Hacktoberfest registration window, since it also feeds the
Reddit/Lemmy launch content that already references Gurnard.

## One-page "what's different" brief

Use as the email body / video-description seed:

> TunaOS is an open-source, bootc-based Enterprise Linux desktop project —
> atomic updates, one transaction, rollback on failure, the whole desktop
> shipped as a signed OCI container image instead of a package-managed
> root filesystem. It builds on multiple bases (AlmaLinux, CentOS Stream,
> Fedora, openSUSE, Arch, Debian, Ubuntu, Gentoo) with the same
> image-mode update model across all of them, and now ships
> daily-rebuilt, keyless-Cosign-signed images with signed SPDX SBOM
> attestations for every published artifact — a genuinely current
> supply-chain story, not a claim.
>
> The project offers **architecture breadth**: ARM64 OCI inputs alongside x86.
> X13s qualification remains a plan, not a claim of support.
> It also offers **desktop breadth**: GNOME, KDE Plasma, COSMIC, Niri,
> and XFCE share the same image-based update model.

## Hardware notes: what to test on ARM vs x86

- **x86_64 (Yellowfin/Bonito)**: standard install, any UEFI machine.
  `sudo bootc switch`/`sudo bootc upgrade` for the atomic-update story.
- **ARM (Lenovo ThinkPad X13s / Qualcomm SC8280XP, Snapdragon 8cx Gen3,
  not X Elite)**: read the [X13s assessment](X13S-SUPPORT.md) before a review.
  The 2026-10-17 investigation observed postmarketOS, not TunaOS.
  It did not test a TunaOS boot or install.
  Generic Bonito GNOME and Fedora 44 bootc images provide ARM64 OCI inputs.
  The build matrix, router, and overlay have no X13s profile.
  The proposed `bonito:gnome-x13s` would use the stock Fedora kernel.
  No implementation exists. Do not promise an ISO, built-in boot configuration,
  or functional peripherals. The assessment records the boot chain and gaps
  in hardware tests.

## Download / checksum verification steps

TunaOS OCI images are signed with Sigstore Cosign's keyless GitHub Actions
identity — see [VERIFY-ARTIFACTS.md](./VERIFY-ARTIFACTS.md) for the full
`cosign verify` / `cosign verify-attestation` walkthrough a technical
reviewer can show on camera. For the live ISOs specifically:

```bash
wget https://download.tunaos.org/live-isos/yellowfin-gnome-latest.iso
./scripts/iso-e2e.sh yellowfin gnome ./yellowfin-gnome-latest.iso  # optional: run the same boot-gate CI uses
```

Every published ISO is boot-verified in QEMU before it's uploaded — see
[TESTING.md](./TESTING.md) for what that gate checks.

## Sequencing

1. Maintainer reviews this kit and the target list.
2. Maintainer sends first-contact notes to DistroTube, Chris Titus Tech,
   The Linux Experiment (in that priority order) — this agent does not
   contact external parties.
3. Track replies on [#1535](https://github.com/tuna-os/tunaOS/issues/1535).
4. Second wave: Michael Horn + ARM-focused channels, once Gurnard has a
   real download or the ARM story alone is judged strong enough to lead
   with.
