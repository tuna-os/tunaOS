<div align="center">
<picture>
  <source srcset="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.webp" type="image/webp">
  <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif" alt="🐟" width="128" height="128">
</picture>

## TunaOS
### *Cloud-native, immutable desktop Linux images*

*One bootc-native desktop experience across Enterprise Linux and community distributions*

---

[![License](https://img.shields.io/github/license/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/blob/main/LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/stargazers)
[![Issues](https://img.shields.io/github/issues/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/issues)
[![Adoption evidence](https://img.shields.io/badge/adoption-0_production%2C_2_evaluation-2ea44f?style=for-the-badge)](ADOPTERS.md)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/MXSTqB8Nv)

</div>

> 🎃 **Hacktoberfest 2026**: We are participating! Looking for your first open-source PR? Check out our [good first issues](https://github.com/tuna-os/tunaOS/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) and join us on Matrix for maintainer office hours in October.

## About TunaOS

TunaOS builds **bootc-based desktop operating systems** with atomic updates and straightforward rollbacks. Choose an Enterprise Linux base for long-term stability or an alternative distribution for a faster release cadence, while keeping the same image-based management model.

[Visit tunaos.org](https://tunaos.org/) or read the [launch announcement](https://tunaos.org/blog/modern-enterprise-linux-desktops-with-tunaos).

- **Modern Desktops**: GNOME, KDE Plasma, COSMIC, Niri, and XFCE — equal first-class options across distribution bases
- **Up-to-Date Desktop Stack**: Fresh desktop features and updates backported to Enterprise and community bases
- **Homebrew**: Baked into the image — all your CLI apps and fonts are just a `brew` command away
- **Flathub by Default**: Full Flathub access out of the box — get any Flatpak available on the net
- **HWE and NVIDIA Options**: Hardware Enablement kernels and NVIDIA drivers + CUDA as image tags

## Choose your image

| Variant | Base OS | Registry Path | Desktops | Architectures |
| :--- | :--- | :--- | :--- | :--- |
| 🐠 **Yellowfin** | AlmaLinux Kitten 10 | `ghcr.io/tuna-os/yellowfin` | GNOME (x86_64 only, see note), KDE, COSMIC, Niri | x86_64, x86_64/v2, arm64 |
| 🐟 **Albacore** | AlmaLinux 10 (RHEL 10) | `ghcr.io/tuna-os/albacore` | GNOME (x86_64 only, see note), KDE, COSMIC, Niri | x86_64, x86_64/v2, arm64 |
| 🍣 **Skipjack** | CentOS Stream 10 | `ghcr.io/tuna-os/skipjack` | GNOME (x86_64 only, see note), KDE, COSMIC, Niri | x86_64, arm64 |
| 🎣 **Bonito** | Fedora 44 | `ghcr.io/tuna-os/bonito` | GNOME, KDE, COSMIC, Niri | x86_64, arm64 |
| 🐦 **Hummingbird** | Fedora Hummingbird (experimental) | `ghcr.io/tuna-os/hummingbird` | Base, GNOME, COSMIC | x86_64; arm64 (base only) |
| 🎏 **Wahoo** | Fedora ELN — EL11 preview (experimental, no codecs) | `ghcr.io/tuna-os/wahoo` | Base, GNOME | x86_64, arm64 |
| 🔒 **Redfin** | Red Hat Enterprise Linux 10 | *Local-Build Only* | GNOME, KDE, COSMIC, Niri, XFCE | x86_64, arm64 |
| 🐟 **Grouper** | Ubuntu 26.04 | `ghcr.io/tuna-os/grouper` | GNOME, KDE, Niri, XFCE | x86_64 |
| 🐟 **Gurnard** | Ubuntu 24.04 (Noble Numbat, experimental) | `ghcr.io/tuna-os/gurnard` | Base, Pantheon | x86_64, arm64 |
| 🚀 **Marlin** | Arch Linux (Rolling) | `ghcr.io/tuna-os/marlin` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64 |
| 🐡 **Flounder** | Debian 13 (Trixie) | `ghcr.io/tuna-os/flounder` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64 |
| ☢️ **Flounder Sid** | Debian Sid (Unstable) | `ghcr.io/tuna-os/flounder:*-sid` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64 |
| 🐉 **Bonito Rawhide** | Fedora Rawhide | `ghcr.io/tuna-os/bonito:*-rawhide` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64, arm64 |
| 🦈 **Sailfin** | openSUSE Tumbleweed | `ghcr.io/tuna-os/sailfin` | GNOME, KDE, Niri, XFCE | x86_64 |
| 🌈 **Guppy** | Gentoo Linux | `ghcr.io/tuna-os/guppy` | GNOME, KDE | x86_64 |
| 🏔️ **Tromsø** | freedesktop-sdk (BuildStream), built in [tuna-os/tromso](https://github.com/tuna-os/tromso) | `ghcr.io/tuna-os/tromso` | KDE | x86_64 |
| 🐭 **XFCE Linux** | freedesktop-sdk (BuildStream), built in [tuna-os/xfce-linux](https://github.com/tuna-os/xfce-linux) | `ghcr.io/tuna-os/xfce-linux` | XFCE | x86_64 |

GNOME on the EL10 variants ships from tunaOS's own GNOME 50 package tier
(built in GitHub Actions, no COPR), which is x86_64 only today, so their
`gnome`/`gnome-hwe` images are x86_64 and `gnome-asahi` is off until the
tier gains aarch64 ([tunaos-packages#673](https://github.com/tuna-os/tunaos-packages/issues/673)).
Every GNOME image, on any base, is GNOME 50 or newer; nothing older promotes.

Tags are `<desktop>[-hardware]` — e.g. `yellowfin:gnome-hwe`,
`albacore:kde-nvidia`. Full tag reference: [docs/IMAGE-TAGS.md](docs/IMAGE-TAGS.md).
Hardware requirements and ARM laptop status: [docs/HARDWARE.md](docs/HARDWARE.md).

> [!NOTE]
> **Redfin (RHEL 10)** is local-build only due to EULA restrictions. To build it locally, run `just build redfin <desktop>` (see [rhel-setup.md](docs/rhel-setup.md)).

## Live build matrix

<!-- build-status:start -->

_Generated from the latest conclusive main-branch build for each variant (cancelled runs are skipped over). A cell is green when its image was successfully promoted to the published tag; **failing** means a job ran and failed; **not reached** means no job asserted the cell at all, usually because an earlier stage stopped it._

| Variant | Green image cells | Latest run | Failing | Not reached |
| :--- | ---: | :--- | :--- | :--- |
| 🐠 `yellowfin` | **9/19** | [❌ 2026-09-04](https://github.com/tuna-os/tunaOS/actions/runs/33837498553) | — | gnome,cosmic,niri,gnome-hwe,gnome-nvidia,gnome-nvidia-hwe,cosmic-hwe,cosmic-nvidia,niri-hwe,niri-nvidia |
| 🐟 `albacore` | **12/19** | [❌ 2026-09-04](https://github.com/tuna-os/tunaOS/actions/runs/33848074014) | — | cosmic,niri,gnome-nvidia-hwe,cosmic-hwe,cosmic-nvidia,niri-hwe,niri-nvidia |
| 🍣 `skipjack` | **7/17** | [❌ 2026-09-04](https://github.com/tuna-os/tunaOS/actions/runs/33878779976) | — | gnome,cosmic,niri,gnome-hwe,gnome-nvidia,gnome-nvidia-hwe,cosmic-hwe,cosmic-nvidia,niri-hwe,niri-nvidia |
| 🎏 `wahoo` | **3/4** | [❌ 2026-08-27](https://github.com/tuna-os/tunaOS/actions/runs/33041330231) | — | cosmic |
| 🎣 `bonito` | **2/16** | [❌ 2026-09-03](https://github.com/tuna-os/tunaOS/actions/runs/33770195451) | — | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce,gnome-hwe,gnome-asahi,gnome-t2,gnome-nvidia,cosmic-nvidia,niri-nvidia |
| 🐦 `hummingbird` | **0/3** | [❌ 2026-09-04](https://github.com/tuna-os/tunaOS/actions/runs/33820627268) | — | base,gnome,cosmic |
| 🦈 `sailfin` | **0/7** | [❌ 2026-09-03](https://github.com/tuna-os/tunaOS/actions/runs/33809632228) | — | base,gnome,gnome-asahi,kde,niri,xfce,cosmic |
| 🌈 `guppy` | **3/4** | [❌ 2026-09-04](https://github.com/tuna-os/tunaOS/actions/runs/33867705086) | — | gnome |
| 🐉 `bonito-rawhide` | **4/14** | [❌ 2026-09-03](https://github.com/tuna-os/tunaOS/actions/runs/33792218775) | — | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce,cosmic-nvidia,niri-nvidia |
| 🐟 `gurnard` | **2/2** | [❌ 2026-09-04](https://github.com/tuna-os/tunaOS/actions/runs/33855672411) | — | — |
| 🐟 `grouper` | **5/7** | [❌ 2026-09-03](https://github.com/tuna-os/tunaOS/actions/runs/33798906941) | — | gnome-zfs,cosmic |
| 🚀 `marlin` | **10/16** | [❌ 2026-09-03](https://github.com/tuna-os/tunaOS/actions/runs/33782342451) | — | cosmic,niri,cosmic-cachyos,niri-cachyos,cosmic-nvidia,niri-nvidia |
| 🐡 `flounder` | **5/7** | [❌ 2026-09-03](https://github.com/tuna-os/tunaOS/actions/runs/33817093302) | — | xfce,xfce-nvidia |
| ☢️ `flounder-sid` | **5/7** | [❌ 2026-09-04](https://github.com/tuna-os/tunaOS/actions/runs/33823985697) | — | xfce,xfce-nvidia |

**Sibling images, built in their own repositories.** These are TunaOS-family bootc images built with BuildStream on freedesktop-sdk rather than from a distribution's packages, so they have no cells in the matrix above and are not scored by `green-criteria.yml`; each repository runs its own build, live-ISO, plain-install and LUKS-install checks. Status is that repository's latest completed main-branch build.

| Image | Built by | Desktop | Latest main build |
| :--- | :--- | :--- | :--- |
| 🏔️ `ghcr.io/tuna-os/tromso` | [tromso](https://github.com/tuna-os/tromso) | KDE | [❌ 2026-09-04](https://github.com/tuna-os/tromso/actions/runs/33838523821) |
| 🐭 `ghcr.io/tuna-os/xfce-linux` | [xfce-linux](https://github.com/tuna-os/xfce-linux) | XFCE | [❌ 2026-09-04](https://github.com/tuna-os/xfce-linux/actions/runs/33824577399) |

**Built 67/142 · composite green 62/145 (47% built)** — of the remainder, **0 failing** and **75 never reached** (no job asserted them). The two are reported separately on purpose: a never-reached cell is untested, not broken. Composite green counts published cells, per [docs/MATRIX-STATUS.md](docs/MATRIX-STATUS.md) and is scored against [`.github/green-criteria.yml`](.github/green-criteria.yml), blocking today on `boots`, `builds`, `desktop`, `no_silent_omissions` — every one of those a cell must satisfy, with skipped and never-tested counting as not green. The full per-axis board is [docs/MATRIX-STATUS.md](docs/MATRIX-STATUS.md). This is a point-in-time CI snapshot, not a support-tier promise.

<!-- build-status:end -->

## Get started

- **Install from an ISO:** [📦 tunaos.org/download](https://tunaos.org/download)
- **Install from Windows (no USB drive needed):** [🪟 wootc installer](https://github.com/tuna-os/wootc) (download from [releases](https://github.com/tuna-os/wootc/releases) / read the [Migration Guide](MIGRATION.md#from-windows-wootc))
- **Build your own ISO in the browser:** [🛠️ tunaos.org/iso-builder](https://tunaos.org/iso-builder)
- **Switch an existing bootc system:**

  ```bash
  sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
  ```

Building media locally, verifying signatures and SBOMs, registry
authentication, and pull troubleshooting: [docs/INSTALL.md](docs/INSTALL.md).

## Contributing

Contributions welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development
environment setup, the build workflow and pre-commit checklist, pull request
guidelines, and an architecture overview.

## Community and support

- 🐛 **Report Issues:** [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [m] **Chat**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)
- 🎮 **Discord:** [TunaOS](https://discord.gg/MXSTqB8Nv)

Related communities: [Universal Blue Discord](https://discord.gg/WEu6BdFEtp) ·
[AlmaLinux Atomic SIG](https://chat.almalinux.org/almalinux/channels/sigatomic)

## Documentation

Start here:

- [User Guide](docs/USER-GUIDE.md) — choosing an image, installing, updating, rolling back, apps, encryption
- [Developer Guide](docs/DEVELOPER-GUIDE.md) — the whole pipeline and its plumbing, with diagrams
- [Installation](docs/INSTALL.md) — building media, verification, registry access
- [Hardware Support](docs/HARDWARE.md) — requirements and ARM laptop status
- [Matrix Status](docs/MATRIX-STATUS.md) — which variant×desktop cells are verified, per quality axis
- [Roadmap](ROADMAP.md) — project direction and feature status
- [Vision](VISION.md) — project philosophy

The full index — every guide, policy, and planning doc — is at
[docs/README.md](docs/README.md).

---

<div align="center">
<img width="400" height="400" alt="Tuna_OS_Logo" src="https://github.com/user-attachments/assets/0c0de438-25ae-429d-b7a5-fe32ea85547f" />

*Made by James in his free time*


*Powered by [Bootc](https://github.com/bootc-dev/bootc)*


<a href="https://github.com/bootc-dev/bootc">
<img width="100" height="130" alt="Bootc_Logo" src="https://raw.githubusercontent.com/containers/common/main/logos/bootc-logo-full-vert.png" />
</a>

---

This repository and many of the [tuna-os](https://github.com/tuna-os) repos are
developed and maintained with **[Hive](https://hive.tunaos.org)**, an AI-driven
development platform orchestrated via [KubeStellar](https://kubestellar.io/).

---

*Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) Community*

*Licensed under [Apache 2.0](https://github.com/tuna-os/tunaOS/blob/main/LICENSE)*

</div>
