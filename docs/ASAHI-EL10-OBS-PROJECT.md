# Open Build Service (OBS) Project for EL10 Asahi Packages (#777)

This document outlines the architecture, package scope, repository configuration, and deployment requirements for establishing the dedicated **Open Build Service (OBS)** project servicing Enterprise Linux 10 (EL10) aarch64 variants (`skipjack`, `yellowfin`, `albacore`, and `bluefin-lts`).

---

## 1. Context & Problem Statement

The CentOS Hyperscale SIG `packages-asahi` repository provides the 16K-page Asahi Linux kernel (`kernel-16k`), `dracut-asahi`, and `update-m1n1` for EL10 aarch64. However, it lacks key userspace utilities required for boot-chain lifecycle management, hardware integration, and audio support:

- **Missing Boot-Chain Components**: `m1n1`, `u-boot-asahi` (`uboot-images-armv8` with `apple_m1` payload), `update-m1n1` kernel installation hooks (`/usr/lib/kernel/install.d/15-update-m1n1.install`).
- **Missing Hardware & Audio Userspace**: `asahi-audio`, `alsa-ucm-asahi`, `speakersafetyd`, `asahi-fwupdate`, `tiny-dfr` (Touch Bar support), `asahi-diagnose`.

Without `update-m1n1` and its kernel-install hook, `bootc upgrade` updates the deployed kernel without refreshing the `m1n1` stage-2 payload on the EFI System Partition (ESP), causing systems to break on kernel upgrades.

---

## 2. OBS Project Design (`build.opensuse.org`)

### Project Target & Platform
- **Target OS**: CentOS Stream 10 / RHEL 10 (`epel-10-aarch64` / `10-stream-aarch64`).
- **Build Infrastructure**: Open Build Service (OBS, `build.opensuse.org`) on native `aarch64` workers with GPG-signed repository metadata output.

### Package Intake & Specification Mapping

| Package | Source Provenance | Target Binary Output | Notes / Role |
|---|---|---|---|
| `m1n1` | Fedora `@asahi` COPR / OBS `home:mrkcee` | `m1n1` | First-stage Apple Silicon bootloader |
| `u-boot-asahi` | Fedora `@asahi/u-boot` COPR | `uboot-images-armv8` | U-Boot bootloader payload with `apple_m1` target |
| `update-m1n1` | CentOS Hyperscale SIG + TunaOS hooks | `update-m1n1` | ESP `boot.bin` sync script + `kernel-install.d` hook |
| `asahi-audio` | EPEL 10 / Fedora `@asahi` | `asahi-audio`, `alsa-ucm-asahi` | PipeWire/ALSA UCM profiles & volume limits |
| `speakersafetyd` | EPEL 10 / Fedora `@asahi` | `speakersafetyd` | Daemon preventing speaker hardware damage |
| `asahi-fwupdate` | Fedora `@asahi` COPR | `asahi-fwupdate` | ESP firmware extraction & update utility |
| `tiny-dfr` | Fedora `@asahi` COPR | `tiny-dfr` | Touch Bar daemon for M1/M2 MacBooks |

---

## 3. Integration into TunaOS Overlay (`build_scripts/overlay/asahi.sh`)

Once the OBS project repository is published at `https://download.opensuse.org/repositories/home:tuna-os:el10-asahi/CentOS_10/`, the `centos` branch in `build_scripts/overlay/asahi.sh` will consume the signed repository:

```bash
# /etc/yum.repos.d/tunaos-el10-asahi-obs.repo
[tunaos-el10-asahi-obs]
name=TunaOS EL10 Asahi Packages (OBS)
baseurl=https://download.opensuse.org/repositories/home:tuna-os:el10-asahi/CentOS_10/
enabled=1
gpgcheck=1
gpgkey=https://download.opensuse.org/repositories/home:tuna-os:el10-asahi/CentOS_10/repodata/repomd.xml.key
```

---

## 4. Verification & Gating

All built EL10 Asahi images (`skipjack:gnome-asahi`, `yellowfin:gnome-asahi`, `albacore:gnome-asahi`) must pass `scripts/verify-asahi-image.sh` with 36/36 checks green before being promoted.
