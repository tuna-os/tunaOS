<div align="center">
<picture>
  <source srcset="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.webp" type="image/webp">
  <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif" alt="🐟" width="128" height="128">
</picture>

## TunaOS
### *Cloud-native, immutable desktop Linux images*

*One bootc-native desktop experience across Enterprise Linux and community distributions*

---

[![License](https://img.shields.io/github/license/tuna-os/tunaOS?style=for-the-badge)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/stargazers)
[![Issues](https://img.shields.io/github/issues/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/issues)
[![Adopters](https://img.shields.io/badge/adopters-0_entries-2ea44f?style=for-the-badge)](ADOPTERS.md)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/MXSTqB8Nv)

</div>

## About TunaOS

TunaOS builds **bootc-based desktop operating systems** with atomic updates and straightforward rollbacks. Choose an Enterprise Linux base for long-term stability or a community distribution for a faster release cadence, while keeping the same image-based management model.

[Visit tunaos.org](https://tunaos.org/) or read the [launch announcement](https://tunaos.org/blog/modern-enterprise-linux-desktops-with-tunaos).

### Features

- **Modern Desktops**: GNOME, KDE Plasma, COSMIC, and Niri — your choice, on Enterprise Linux
- **Latest GNOME**: Don't get stuck on a 3-year-old GNOME. We backport the latest desktop features to the Enterprise Desktop
- **Homebrew**: Baked into the image — all your CLI apps and fonts are just a `brew` command away
- **Flathub by Default**: Full Flathub access out of the box — get any Flatpak available on the net
- **HWE Option**: Hardware Enablement kernel for newer hardware support
- **NVIDIA Option**: NVIDIA drivers and CUDA for graphics and AI workflows

## Images and variants

TunaOS provides a variety of bootc-based operating system images. Use the table below to choose your base distribution and desktop environment.

### Live build matrix

<!-- build-status:start -->

_Generated from the latest completed main-branch build for each variant. A cell is green when its image was successfully promoted to the published tag._

| Variant | Green image cells | Latest run | Blocked or failing tags |
| :--- | ---: | :--- | :--- |
| 🐠 `yellowfin` | **0/20** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31761128357) | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce,gnome-hwe,gnome-asahi,gnome-nvidia,gnome-nvidia-hwe,cosmic-hwe,cosmic-nvidia,kde-hwe,kde-nvidia,niri-hwe,niri-nvidia,xfce-hwe,xfce-nvidia |
| 🐟 `albacore` | **0/20** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31760883732) | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce,gnome-hwe,gnome-asahi,gnome-nvidia,gnome-nvidia-hwe,cosmic-hwe,cosmic-nvidia,kde-hwe,kde-nvidia,niri-hwe,niri-nvidia,xfce-hwe,xfce-nvidia |
| 🍣 `skipjack` | **0/18** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31761065248) | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce,gnome-hwe,gnome-asahi,gnome-nvidia,gnome-nvidia-hwe,cosmic-hwe,cosmic-nvidia,kde-hwe,kde-nvidia,niri-hwe,niri-nvidia |
| 🎣 `bonito` | **0/15** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31760970659) | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce,gnome-hwe,gnome-asahi,gnome-nvidia,cosmic-nvidia,kde-nvidia,niri-nvidia,xfce-nvidia |
| 🐦 `hummingbird` | **0/5** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31760893054) | base,gnome,kde,niri,cosmic |
| 🦈 `sailfin` | **0/7** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31761111469) | base,gnome,gnome-asahi,kde,niri,xfce,cosmic |
| 🌈 `guppy` | **0/4** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31761089431) | base,gnome,kde,xfce |
| 🐉 `bonito-rawhide` | **0/14** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31761022319) | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce,gnome-hwe,gnome-nvidia,cosmic-nvidia,kde-nvidia,niri-nvidia,xfce-nvidia |
| 🐟 `gurnard` | **0/2** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31760817151) | base,pantheon |
| 🐟 `grouper` | **0/7** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31760884612) | base,gnome,gnome-asahi,gnome-zfs,kde,cosmic,xfce |
| 🚀 `marlin` | **0/12** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31761124101) | base,gnome,gnome-asahi,kde,cosmic,niri,xfce,gnome-cachyos,kde-cachyos,cosmic-cachyos,niri-cachyos,xfce-cachyos |
| 🐡 `flounder` | **0/5** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31761046911) | base,gnome,gnome-asahi,kde,xfce |
| ☢️ `flounder-sid` | **0/4** | [❌ 2026-08-14](https://github.com/hanthor/tunaos-999/actions/runs/31760891675) | base,gnome,kde,xfce |

**Current image coverage: 0/133 cells (0%).** This is a point-in-time CI snapshot, not a support-tier promise.

<!-- build-status:end -->

| Variant | Base OS | Registry Path | Desktops | Architectures |
| :--- | :--- | :--- | :--- | :--- |
| 🐠 **Yellowfin** | AlmaLinux Kitten 10 | `ghcr.io/tuna-os/yellowfin` | GNOME, KDE, COSMIC, Niri | x86_64, x86_64/v2, arm64 |
| 🐟 **Albacore** | AlmaLinux 10 (RHEL 10) | `ghcr.io/tuna-os/albacore` | GNOME, KDE, COSMIC, Niri | x86_64, x86_64/v2, arm64 |
| 🍣 **Skipjack** | CentOS Stream 10 | `ghcr.io/tuna-os/skipjack` | GNOME, KDE, COSMIC, Niri | x86_64, arm64 |
| 🎣 **Bonito** | Fedora 44 | `ghcr.io/tuna-os/bonito` | GNOME, KDE, COSMIC, Niri | x86_64, arm64 |
| 🐦 **Hummingbird** | Fedora Hummingbird (experimental) | `ghcr.io/tuna-os/hummingbird` | Base only | x86_64, arm64 |
| 🔒 **Redfin** | Red Hat Enterprise Linux 10 | *Local-Build Only* | GNOME, KDE, COSMIC, Niri, XFCE | x86_64, arm64 |
| 🐟 **Gurnard** | Ubuntu 24.04 Noble (experimental) | `ghcr.io/tuna-os/gurnard` | Pantheon | x86_64, arm64 |
| 🐟 **Grouper** | Ubuntu 26.04 | `ghcr.io/tuna-os/grouper` | GNOME, KDE, Niri, XFCE | x86_64 |
| 🚀 **Marlin** | Arch Linux (Rolling) | `ghcr.io/tuna-os/marlin` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64 |
| 🐡 **Flounder** | Debian 13 (Trixie) | `ghcr.io/tuna-os/flounder` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64 |
| ☢️ **Flounder Sid** | Debian Sid (Unstable) | `ghcr.io/tuna-os/flounder:*-sid` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64 |
| 🐉 **Bonito Rawhide** | Fedora Rawhide | `ghcr.io/tuna-os/bonito:*-rawhide` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64, arm64 |
| 🦈 **Sailfin** | openSUSE Tumbleweed | `ghcr.io/tuna-os/sailfin` | GNOME, KDE, Niri, XFCE | x86_64 |
| 🌈 **Guppy** | Gentoo Linux | `ghcr.io/tuna-os/guppy` | GNOME, KDE | x86_64 |

> [!NOTE]
> **Redfin (RHEL 10)** is local-build only due to EULA restrictions. To build it locally, run `just build redfin <desktop>` (see [rhel-setup.md](docs/rhel-setup.md)).

### Suffix Rules (Image Tags)

Image tags are constructed as `<desktop>[-hardware]`:

1. **Desktop Suffixes**:
   * `gnome`: GNOME (stable)
   * `kde`: KDE Plasma
   * `cosmic`: COSMIC Desktop
   * `niri`: Niri (tiling Wayland compositor)
   * `xfce`: XFCE (Wayland experimental)
   * `pantheon`: Pantheon (Gurnard experimental)
   * `base`: Plain system image with no desktop environment pre-installed (available for most variants)

2. **Hardware Suffixes** (append to any desktop suffix):
   * *(none)*: Standard generic kernel build
   * `-hwe`: Hardware Enablement (newer kernel stack)
   * `-nvidia`: NVIDIA drivers + CUDA pre-configured
   * `-nvidia-hwe`: NVIDIA drivers on HWE kernel stack

*Example tags:* `yellowfin:gnome-hwe`, `albacore:kde-nvidia`, `marlin:cosmic`

---

## System requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | x86_64, ARM64 | x86_64, ARM64 |
| **RAM** | 4 GB | 8 GB+ |
| **Storage** | 20 GB | 50 GB+ |

---

## Installation

### Use a pre-built ISO

Browse the currently published installation media on the download page:

**[📦 tunaos.org/download](https://tunaos.org/download)**

### Build your own ISO or VM image

**In your browser — no tools, no root, nothing uploaded:**

**[🛠️ tunaos.org/iso-builder](https://tunaos.org/iso-builder)** — point it
at any TunaOS image (or your own bootc image), pick your flatpaks, and it
authors a bootable live ISO entirely in WebAssembly using the same
[tacklebox](https://github.com/tuna-os/tacklebox) engine CI uses.
[User guide](https://tunaos.org/docs/iso-builder).

**Or locally with [tacklebox](https://github.com/tuna-os/tacklebox):**

```bash
# ISO (requires root)
sudo tacklebox build --iso tunaos-yellowfin-gnome.iso \
  --bootable-environment-image ghcr.io/tuna-os/yellowfin:gnome \
  --bootable-environment-desktop gnome \
  --output-base .build/iso
```

Or use the included helper script:

```bash
sudo ./scripts/build-iso-tacklebox.sh yellowfin gnome ghcr gnome
```

For QCOW2 VM images, use bootc directly:

```bash
# QCOW2 (VM image)
sudo bootc image build-to-qcow2 \
  --output-format qcow2 \
  ghcr.io/tuna-os/yellowfin:gnome
```

### Switch an existing system

If you're already running a compatible bootc system:

```bash
sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
```

## Container registry authentication

Images are published on GitHub Container Registry (GHCR). To pull images with `bootc` or `podman`:

```bash
# Authenticate to GHCR (requires a GitHub personal access token with read:packages scope)
echo "$GITHUB_TOKEN" | podman login ghcr.io -u YOUR_USERNAME --password-stdin

# Or use the GitHub CLI
gh auth token | podman login ghcr.io -u YOUR_USERNAME --password-stdin
```

See [GitHub Container Registry docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) for more details.

## Contributing

Contributions welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) for:
- Development environment setup
- Build workflow and pre-commit checklist
- Pull request guidelines
- Architecture overview

## Community and support

- 🐛 **Report Issues:** [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [m] **Chat**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)
- 🎮 **Discord:** [TunaOS](https://discord.gg/MXSTqB8Nv)

Related Communities:
- 🎮 **Discord:** [Universal Blue Community](https://discord.gg/WEu6BdFEtp)
- 💬 **AlmaLinux Atomic SIG:** [AlmaLinux Atomic SIG](https://chat.almalinux.org/almalinux/channels/sigatomic)

## Documentation

### Project Docs
- [TunaOS Blog](https://tunaos.org/blog/modern-enterprise-linux-desktops-with-tunaos) — launch announcement and design philosophy comparison
- [Contributor Guide](CONTRIBUTING.md) — how to set up, build, and contribute
- [Roll Your Own Guide](docs/ROLL_YOUR_OWN.md) — build your own custom TunaOS variant
- [Agent Guide](docs/AGENT_GUIDE.md) — complete architecture and contributor reference
- [Build Pipeline](docs/build-pipeline.md) — CI/CD workflow overview
- [Testing Guide](docs/TESTING.md) — ISO end-to-end test harness
- [Secure Boot](docs/SECURE-BOOT.md) — which variants support Secure Boot out of the box
- [Improvement Plan](docs/IMPROVEMENT_PLAN.md) — roadmap and development progress
- [Redfin Setup](docs/rhel-setup.md) — RHEL 10 local-build instructions
- [Developer Docs](https://tunaos.org/docs/dev/introduction) — build and contribution guide

### Policies & Planning
- [Roadmap](ROADMAP.md) — project direction and feature status
- [Versioning](VERSIONING.md) — tag scheme and stability tiers
- [Migration Guide](MIGRATION.md) — switching from other distros
- [Security Policy](SECURITY.md) — vulnerability reporting and supported versions
- [Adopters](ADOPTERS.md) — organizations using TunaOS
- [Code of Conduct](CODE_OF_CONDUCT.md) — community standards

### Community & Governance
- [Community](COMMUNITY.md) — contribution ladder, metrics, communication
- [Maintainers](MAINTAINERS.md) — maintainer playbook and bus factor plan

### External Resources
- [AlmaLinux Kitten 10 Differences](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#how-is-almalinux-os-kitten-different-from-centos-stream)
- [Project Bluefin Documentation](https://docs.projectbluefin.io)
- [Universal Blue](https://universal-blue.org/)
- [bootc](https://github.com/bootc-dev/bootc)

---

<div align="center">
<img width="400" height="400" alt="Tuna_OS_Logo" src="https://github.com/user-attachments/assets/0c0de438-25ae-429d-b7a5-fe32ea85547f" />

*Made by James in his free time*


*Powered by [Bootc](https://github.com/bootc-dev/bootc)*


<a href="https://github.com/bootc-dev/bootc">
<img width="100" height="130" alt="Bootc_Logo" src="https://raw.githubusercontent.com/containers/common/main/logos/bootc-logo-full-vert.png" />
</a>

---

### 🤖 Powered by KubeStellar / Hive

This repository and many of the [tuna-os](https://github.com/tuna-os) repositories are developed and maintained using **[Hive](https://hive.tunaos.org)** — an AI-driven development platform orchestrated via [KubeStellar](https://kubestellar.io/).

Hive deploys a suite of specialized AI agents (guide, architect, sec-check, quality, ci-maintainer, strategist) onto a local Kubernetes cluster. These agents triage issues, implement fixes, review PRs, manage CI pipelines, and maintain documentation — all working autonomously through GitHub.

<img width="100" alt="Hive" src="https://avatars.githubusercontent.com/in/3942065" />

Every commit, PR, and issue in this repo benefits from multi-agent collaboration coordinated through Hive.

*Learn more: [hive.tunaos.org](https://hive.tunaos.org) | [KubeStellar](https://kubestellar.io/)*

---

*Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) Community*

*Licensed under [Apache 2.0](LICENSE)*

</div>
