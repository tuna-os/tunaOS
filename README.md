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

TunaOS builds **bootc-based desktop operating systems** with atomic updates and straightforward rollbacks. Choose an Enterprise Linux base for long-term stability or a community distribution for a faster release cadence, while keeping the same image-based management model.

[Visit tunaos.org](https://tunaos.org/) or read the [launch announcement](https://tunaos.org/blog/modern-enterprise-linux-desktops-with-tunaos).

- **Modern Desktops**: GNOME, KDE Plasma, COSMIC, Niri, and XFCE — equal first-class options across distribution bases
- **Up-to-Date Desktop Stack**: Fresh desktop features and updates backported to Enterprise and community bases
- **Homebrew**: Baked into the image — all your CLI apps and fonts are just a `brew` command away
- **Flathub by Default**: Full Flathub access out of the box — get any Flatpak available on the net
- **HWE and NVIDIA Options**: Hardware Enablement kernels and NVIDIA drivers + CUDA as image tags

## Choose your image

| Variant | Base OS | Registry Path | Desktops | Architectures |
| :--- | :--- | :--- | :--- | :--- |
| 🐠 **Yellowfin** | AlmaLinux Kitten 10 | `ghcr.io/tuna-os/yellowfin` | GNOME, KDE, COSMIC, Niri | x86_64, x86_64/v2, arm64 |
| 🐟 **Albacore** | AlmaLinux 10 (RHEL 10) | `ghcr.io/tuna-os/albacore` | GNOME, KDE, COSMIC, Niri | x86_64, x86_64/v2, arm64 |
| 🍣 **Skipjack** | CentOS Stream 10 | `ghcr.io/tuna-os/skipjack` | GNOME, KDE, COSMIC, Niri | x86_64, arm64 |
| 🎣 **Bonito** | Fedora 44 | `ghcr.io/tuna-os/bonito` | GNOME, KDE, COSMIC, Niri | x86_64, arm64 |
| 🐦 **Hummingbird** | Fedora Hummingbird (experimental) | `ghcr.io/tuna-os/hummingbird` | Base, GNOME, KDE, COSMIC, Niri | x86_64, arm64 |
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
| 🐠 `yellowfin` | **1/20** | [✅ 2026-08-19](https://github.com/tuna-os/tunaOS/actions/runs/32254285223) | — | base,base-hwe,base-nvidia,cosmic,kde,niri,xfce,gnome-hwe,gnome-asahi,gnome-nvidia,gnome-nvidia-hwe,cosmic-hwe,cosmic-nvidia,kde-hwe,kde-nvidia,niri-hwe,niri-nvidia,xfce-hwe,xfce-nvidia |
| 🐟 `albacore` | **6/20** | [❌ 2026-08-18](https://github.com/tuna-os/tunaOS/actions/runs/32143809963) | — | base,base-nvidia,niri,gnome-hwe,gnome-nvidia,gnome-nvidia-hwe,cosmic-hwe,cosmic-nvidia,kde-hwe,kde-nvidia,niri-hwe,niri-nvidia,xfce-hwe,xfce-nvidia |
| 🍣 `skipjack` | **10/18** | [❌ 2026-08-18](https://github.com/tuna-os/tunaOS/actions/runs/32090785200) | — | gnome,gnome-hwe,gnome-asahi,gnome-nvidia,gnome-nvidia-hwe,cosmic-nvidia,kde-nvidia,niri-nvidia |
| 🎣 `bonito` | **5/16** | [❌ 2026-08-18](https://github.com/tuna-os/tunaOS/actions/runs/32091020905) | — | base-nvidia,gnome,niri,gnome-hwe,gnome-asahi,gnome-t2,gnome-nvidia,cosmic-nvidia,kde-nvidia,niri-nvidia,xfce-nvidia |
| 🐦 `hummingbird` | **1/5** | [❌ 2026-08-18](https://github.com/tuna-os/tunaOS/actions/runs/32144269992) | — | gnome,kde,niri,cosmic |
| 🦈 `sailfin` | **0/7** | [❌ 2026-08-19](https://github.com/tuna-os/tunaOS/actions/runs/32207972605) | — | base,gnome,gnome-asahi,kde,niri,xfce,cosmic |
| 🌈 `guppy` | **0/4** | [❌ 2026-08-19](https://github.com/tuna-os/tunaOS/actions/runs/32207524392) | — | base,gnome,kde,xfce |
| 🐉 `bonito-rawhide` | **0/14** | [❌ 2026-08-19](https://github.com/tuna-os/tunaOS/actions/runs/32207826157) | — | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce,gnome-hwe,gnome-nvidia,cosmic-nvidia,kde-nvidia,niri-nvidia,xfce-nvidia |
| 🐟 `gurnard` | **2/2** | [❌ 2026-08-19](https://github.com/tuna-os/tunaOS/actions/runs/32208039249) | — | — |
| 🐟 `grouper` | **2/7** | [❌ 2026-08-17](https://github.com/tuna-os/tunaOS/actions/runs/31987613412) | — | gnome,gnome-zfs,kde,cosmic,xfce |
| 🚀 `marlin` | **16/16** | [❌ 2026-08-18](https://github.com/tuna-os/tunaOS/actions/runs/32091076264) | — | — |
| 🐡 `flounder` | **1/7** | [❌ 2026-08-17](https://github.com/tuna-os/tunaOS/actions/runs/31987631533) | — | gnome,kde,xfce,gnome-nvidia,kde-nvidia,xfce-nvidia |
| ☢️ `flounder-sid` | **3/7** | [❌ 2026-08-19](https://github.com/tuna-os/tunaOS/actions/runs/32207827017) | — | gnome,kde,xfce,xfce-nvidia |

**Built 47/143 · composite green 47/143 (32%)** — of the remainder, **0 failing** and **96 never reached** (no job asserted them). The two are reported separately on purpose: a never-reached cell is untested, not broken. Composite green is scored against [`.github/green-criteria.yml`](.github/green-criteria.yml) (blocking today: `builds` + `boots` — a cell must promote AND pass its boot Gate; the full per-axis board is [docs/MATRIX-STATUS.md](docs/MATRIX-STATUS.md)). This is a point-in-time CI snapshot, not a support-tier promise.

<!-- build-status:end -->

## Get started

- **Install from an ISO:** [📦 tunaos.org/download](https://tunaos.org/download)
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
