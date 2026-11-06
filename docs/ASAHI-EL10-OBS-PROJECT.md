# Open Build Service (OBS) Project for EL10 Asahi Packages (#777)

This document outlines the architecture, package scope, repository configuration, and deployment requirements for establishing the dedicated **Open Build Service (OBS)** project servicing Enterprise Linux 10 (EL10) aarch64 variants (`skipjack`, `yellowfin`, `albacore`, and `bluefin-lts`).

---

## 1. Context & Problem Statement

The CentOS Hyperscale SIG `packages-asahi` repository provides the 16K-page Asahi Linux kernel (`kernel-16k`), `dracut-asahi`, and `update-m1n1` for EL10 aarch64. The original gap analysis listed these components. Some are now available; section 4 records the measured sources:

- **Original Boot-Chain Gaps**: `m1n1`, `u-boot-asahi` (`uboot-images-armv8` with `apple_m1` payload), `update-m1n1` kernel installation hooks (`/usr/lib/kernel/install.d/15-update-m1n1.install`).
- **Original Hardware & Audio Gaps**: `asahi-audio`, `alsa-ucm-asahi`, `speakersafetyd`, `asahi-fwupdate`, `tiny-dfr` (Touch Bar support), `asahi-diagnose`.

Kernel-install hooks do not run on `bootc upgrade`. TunaOS ships
`asahi-bootbin-sync.service` to refresh the ESP payload after deployment
(see `build_scripts/asahi/install-bootbin-sync.sh`, #779). A missing
package hook is a gap in the package, not evidence that this deployment service
is absent.

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

Both build promotion and the daily sweep use `scripts/verify-asahi-image.sh`.
Packaged runtime components are hard requirements, including `asahi-diagnose`
from Hyperscale's `asahi-scripts` (`/usr/sbin/asahi-diagnose`, accepted alongside
Fedora's `/usr/bin` layout). The overlay needs that package.

The maintainer decision in [#1411](https://github.com/tuna-os/tunaos/issues/1411)
allows only target-unavailable components to warn. EL10 warnings for
`apple-isp.ko`, the `update-m1n1` kernel hook, `tiny-dfr`, and its unit link to
[#4259](https://github.com/tuna-os/tunaos/issues/4259). Checks for other families
remain strict. Restore strict checks for EL10 as the packages become available.

Evidence from 2026-11-03:

- [Metadata from Hyperscale for aarch64](https://mirror.stream.centos.org/SIGs/10-stream/hyperscale/aarch64/packages-asahi/repodata/repomd.xml)
  lists `asahi-scripts-20250426.1-1.hs+asahi.el10` with the diagnostic in
  `/usr/sbin`; `update-m1n1` filelists contain no kernel-install hook.
- [EPEL10 aarch64 metadata](https://dl.fedoraproject.org/pub/epel/10/Everything/aarch64/repodata/repomd.xml)
  and Hyperscale list no `tiny-dfr` package.
- The URL for the proposed OBS repository returns HTTP 404. It is a design,
  not a package source the overlay can enable today.
