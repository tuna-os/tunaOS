# Linux YouTuber Review Kit

> Status: **draft** — for maintainer review. Contact with creators is a
> maintainer action; this agent does not reach out to external parties.
> Issue: [#1535](https://github.com/tuna-os/tunaOS/issues/1535).
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

Live checks verified these downloads on 2026-08-14. See **Known gap** below before you send anything.

| Story | Variant | Download | Notes |
|---|---|---|---|
| Enterprise Linux desktop, stable | Yellowfin GNOME | [yellowfin-gnome-latest.iso](https://download.tunaos.org/live-isos/yellowfin-gnome-latest.iso) | The flagship, most-tested variant |
| Fedora desktop | Bonito GNOME | [bonito-gnome-latest.iso](https://download.tunaos.org/live-isos/bonito-gnome-latest.iso) | Bonito is still Beta (GA tracked in #272) — say so if it comes up |
| Snapdragon X Elite / ARM laptop | bonito-x13s | [bonito-x13s-latest.iso](https://download.tunaos.org/bonito-x13s/bonito-x13s-latest.iso) | Rebuilt automatically on every push — always current |
| Snapdragon X Elite / ARM laptop (Bluefin-based) | dakota-x13s | [x13s-live-latest.iso](https://download.tunaos.org/dakota-x13s/x13s-live-latest.iso) | Alpha; tracks upstream Project Bluefin Dakota |

**Before you send links**, check https://tunaos.org/download.
These links are convenience pointers, not pinned artifacts. Freshness
depends on which pipeline touched them last.

## Known gap: Gurnard has no downloadable ISO yet

The issue assumed an ISO for Gurnard Pantheon was ready. The team checked against `tunaos.org/iso-index.json` and `download.tunaos.org`. No Gurnard entries exist.

Gurnard has `build_image: true` but no `build_iso: true` in `.github/build-config.yml`. The pipeline builds only the container image. This matches Gurnard's status in [`ROADMAP.md`](../ROADMAP.md): **Experimental**.

The proposed `bonito:niri` ISO does not exist either. Only `bonito-gnome` and `bonito-gnome-nvidia` are live.

**Recommendation**: Do not include Gurnard in the first wave. Lead with Yellowfin and Bonito (stable downloads) and the ARM story (bonito-x13s and dakota-x13s). Revisit Gurnard once ISO builds land.

## One-page "what's different" brief

Use as the email body / video-description seed:

```text
TunaOS is an open-source, bootc-based Enterprise Linux desktop. It provides atomic updates, single-transaction updates, and rollback on failure. The desktop ships as a signed OCI container image. It builds on multiple base distributions (AlmaLinux, CentOS Stream, Fedora, openSUSE, Arch, Debian, Ubuntu, Gentoo). The project ships keyless-signed images with SPDX SBOM attestations.

Key review angles:
1. Hardware breadth: runs on Snapdragon X Elite ARM laptops (ThinkPad X13s) and x86_64.
2. Desktop breadth: GNOME, KDE Plasma, COSMIC, Niri, and XFCE.
```

## Hardware notes: what to test on ARM vs x86

- **x86_64 (Yellowfin/Bonito)**: Standard install on UEFI machines. Test `sudo bootc switch` and `sudo bootc upgrade` for atomic updates.
- **ARM (bonito-x13s/dakota-x13s on ThinkPad X13s)**: The image includes kernel arguments and device tree files. The upstream `jlinton/x13s` kernel provides hardware enablement.

## Download / checksum verification steps

The pipeline in CI signs images for TunaOS with Sigstore Cosign. See [`VERIFY-ARTIFACTS.md`](./VERIFY-ARTIFACTS.md) for the verification guide. For the live ISOs specifically:

```bash
wget https://download.tunaos.org/live-isos/yellowfin-gnome-latest.iso
./scripts/iso-e2e.sh yellowfin gnome ./yellowfin-gnome-latest.iso  # optional: run the same boot-gate CI uses
```

Every published ISO passes boot checks in QEMU before publication. See [`TESTING.md`](./TESTING.md) for test details.

## Sequencing

1. Maintainer reviews this kit and the target list.
2. Maintainer sends notes to DistroTube, Chris Titus Tech, and The Linux Experiment.
3. Track replies on [#1535](https://github.com/tuna-os/tunaOS/issues/1535).
4. Second wave: Contact Michael Horn and ARM channels once Gurnard or ARM is ready.
