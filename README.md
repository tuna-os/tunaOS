
<div align="center">
<picture>
  <source srcset="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.webp" type="image/webp">
  <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif" alt="🐟" width="128" height="128">
</picture>

## TunaOS
### *A Collection of Cloud-Native Enterprise Linux OS Images*

*Bootc-based desktop Linux images built on AlmaLinux, CentOS Stream, and Fedora*

---

[![License](https://img.shields.io/github/license/tuna-os/tunaOS?style=for-the-badge)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/stargazers)
[![Issues](https://img.shields.io/github/issues/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/issues)
[![Adopters](https://img.shields.io/badge/adopters-0_entries-2ea44f?style=for-the-badge)](ADOPTERS.md)

</div>

## 🚀 About TunaOS

TunaOS is a curated collection of **bootc-based desktop operating systems** built on modern container technology. The goal is to bring a modern desktop experience to Enterprise Linux — stable, immutable, and up-to-date. Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) community.

### Features

- **Modern Desktops**: GNOME, KDE Plasma, COSMIC, and Niri — your choice, on Enterprise Linux
- **Latest GNOME**: Don't get stuck on a 3-year-old GNOME. We backport the latest desktop features to the Enterprise Desktop
- **Homebrew**: Baked into the image — all your CLI apps and fonts are just a `brew` command away
- **Flathub by Default**: Full Flathub access out of the box — get any Flatpak available on the net
- **HWE Option**: Hardware Enablement kernel for newer hardware support
- **NVIDIA Option**: NVIDIA drivers and CUDA for graphics and AI workflows

## 🐠 Images

<div align="center">

<img width="328" height="318" alt="1000016351" src="https://github.com/user-attachments/assets/759fc093-baf0-4959-900a-5e9c2098f745" />
</div>

### Desktops

Each variant ships multiple desktop environments:

| Tag suffix | Desktop |
|---|---|
| `gnome` | GNOME (stable) |

| `kde` | KDE Plasma |
| `cosmic` | COSMIC Desktop |
| `niri` | Niri (tiling Wayland compositor) |
| `xfce` | XFCE 4.20 (Wayland, experimental) — xfwl4 compositor |

### Hardware Variants

Append to any desktop tag:

| Suffix | Description |
|---|---|
| *(none)* | Standard build |
| `-hwe` | Hardware Enablement — newer kernel stack |
| `-nvidia` | NVIDIA drivers + CUDA |
| `-nvidia-hwe` | NVIDIA on HWE kernel |

Example: `ghcr.io/tuna-os/yellowfin:gnome-hwe`, `ghcr.io/tuna-os/albacore:kde-nvidia`

---

### 🐠 Yellowfin (AlmaLinux Kitten 10)

**Base:** [AlmaLinux Kitten 10](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#container-images) — the closest to upstream CentOS Stream

**Platforms:** x86_64, x86_64/v2 (pre-2013 CPUs), ARM64

```
ghcr.io/tuna-os/yellowfin:gnome
ghcr.io/tuna-os/yellowfin:gnome-hwe
ghcr.io/tuna-os/yellowfin:kde
ghcr.io/tuna-os/yellowfin:niri
ghcr.io/tuna-os/yellowfin:cosmic
```

- ✨ **x86_64/v2** microarchitecture support
- 🖥️ **SPICE support** for qemu/libvirt virtualization
- 🔄 **Compatible with upstream** — Kitten tracks CentOS Stream

---

### 🐟 Albacore (AlmaLinux 10)

**Base:** [AlmaLinux 10](https://almalinux.org/blog/2025-05-27-welcoming-almalinux-10/) — stable, RHEL-compatible

**Platforms:** x86_64, x86_64/v2, ARM64

```
ghcr.io/tuna-os/albacore:gnome
ghcr.io/tuna-os/albacore:gnome-hwe
ghcr.io/tuna-os/albacore:kde
ghcr.io/tuna-os/albacore:niri
ghcr.io/tuna-os/albacore:cosmic
ghcr.io/tuna-os/albacore:xfce
```

- ✨ **x86_64/v2** microarchitecture support
- 🖥️ **SPICE support** for qemu/libvirt virtualization
- 🏢 **Enterprise stability** — follows RHEL lifecycle

---

### 🍣 Skipjack (CentOS Stream 10)

**Base:** CentOS Stream 10 — the upstream of RHEL

**Platforms:** x86_64, ARM64

```
ghcr.io/tuna-os/skipjack:gnome
ghcr.io/tuna-os/skipjack:kde
ghcr.io/tuna-os/skipjack:niri
ghcr.io/tuna-os/skipjack:cosmic
```

---

> [!NOTE]
> Bonito is still a work in progress and may not be fully functional

### 🎣 Bonito (Fedora 44)

**Base:** Fedora 44 — cutting-edge Fedora on bootc

**Platforms:** x86_64, ARM64

```
ghcr.io/tuna-os/bonito:gnome
ghcr.io/tuna-os/bonito:kde
ghcr.io/tuna-os/bonito:niri
ghcr.io/tuna-os/bonito:cosmic
```

---

### 🔒 Redfin (RHEL 10) — Local-Build Only

**Base:** Red Hat Enterprise Linux 10 — fully supported, subscription-based

**Platforms:** x86_64, ARM64

**Desktops:** GNOME, GNOME 50, KDE, COSMIC, Niri, XFCE (all desktops supported)

> [!IMPORTANT]
> Due to the RHEL EULA, Redfin images **cannot be publicly distributed**. This variant is local-build only.
> For a freely redistributable RHEL-compatible alternative, use Albacore (AlmaLinux 10).

See [`docs/rhel-setup.md`](docs/rhel-setup.md) for prerequisites, authentication, and build instructions.

```bash
just build redfin gnome
just build redfin kde
just build redfin cosmic
just build redfin niri
just build redfin all
```


### 🐟 Grouper (Ubuntu 26.04 Resolute Raccoon)

**Base:** [Ubuntu 26.04](https://ubuntu.com/) — cloud-native Ubuntu on bootc

**Platforms:** x86_64

**Desktops:** GNOME, KDE, Niri, XFCE (+ base)

> [!NOTE]
> Grouper is an experimental Ubuntu variant using `Containerfile.ubuntu`. COSMIC is not yet supported on Ubuntu.

```
ghcr.io/tuna-os/grouper:base
ghcr.io/tuna-os/grouper:gnome
ghcr.io/tuna-os/grouper:kde
ghcr.io/tuna-os/grouper:niri
ghcr.io/tuna-os/grouper:xfce
```

### 🚀 Marlin (Arch Linux — Rolling)

**Base:** [Arch Linux](https://archlinux.org/) — rolling-release, bleeding-edge packages

**Platforms:** x86_64

**Desktops:** GNOME, KDE, COSMIC, Niri, XFCE (+ base)

> [!NOTE]
> Marlin compiles bootc from source (Arch doesn't package it). Builds take longer than EL10/Fedora variants.

```
ghcr.io/tuna-os/marlin:base
ghcr.io/tuna-os/marlin:gnome
ghcr.io/tuna-os/marlin:kde
ghcr.io/tuna-os/marlin:cosmic
ghcr.io/tuna-os/marlin:niri
ghcr.io/tuna-os/marlin:xfce
```

---

### 🛡️ Flounder (Debian 13 Trixie)

**Base:** [Debian 13 Trixie](https://www.debian.org/releases/trixie/) — stable

**Platforms:** x86_64

> [!WARNING]
> Flounder is **blocked** on Debian Trixie due to `ostree` version requirement (Trixie ships ostree 2025.2, bootc requires >= 2025.3).

---

### ☢️ Flounder Sid (Debian Sid — Unstable)

**Base:** [Debian Sid](https://www.debian.org/releases/sid/) — rolling/unstable

**Platforms:** x86_64

```
ghcr.io/tuna-os/flounder-sid:base
ghcr.io/tuna-os/flounder-sid:gnome
ghcr.io/tuna-os/flounder-sid:kde
ghcr.io/tuna-os/flounder-sid:cosmic
ghcr.io/tuna-os/flounder-sid:niri
ghcr.io/tuna-os/flounder-sid:xfce
```

---

### 🐉 Bonito Rawhide (Fedora Rawhide)

**Base:** [Fedora Rawhide](https://docs.fedoraproject.org/en-US/releases/rawhide/) — rolling Fedora development

**Platforms:** x86_64, ARM64

**Desktops:** GNOME, KDE, COSMIC, Niri, XFCE (including HWE and NVIDIA variants)

> [!NOTE]
> Rawhide is the development branch of Fedora — expect frequent updates and occasional breakage.

```
ghcr.io/tuna-os/bonito-rawhide:base
ghcr.io/tuna-os/bonito-rawhide:gnome
ghcr.io/tuna-os/bonito-rawhide:kde
ghcr.io/tuna-os/bonito-rawhide:niri
ghcr.io/tuna-os/bonito-rawhide:xfce
```

---


## 📋 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | x86_64, ARM64 | x86_64, ARM64 |
| **RAM** | 4 GB | 8 GB+ |
| **Storage** | 20 GB | 50 GB+ |

---

## 🛠️ Installation

### Use a pre-built ISO

ISOs are published every two weeks for `gnome` and `gnome-hwe` flavors of Yellowfin and Albacore:

| Variant | GNOME | GNOME (HWE) |
|---------|-------|-------------|
| **Albacore** | [albacore-gnome-latest.iso](https://download.tunaos.org/live-isos/albacore-gnome-latest.iso) | [albacore-gnome-hwe-latest.iso](https://download.tunaos.org/live-isos/albacore-gnome-hwe-latest.iso) |
| **Yellowfin** | [yellowfin-gnome-latest.iso](https://download.tunaos.org/live-isos/yellowfin-gnome-latest.iso) | [yellowfin-gnome-hwe-latest.iso](https://download.tunaos.org/live-isos/yellowfin-gnome-hwe-latest.iso) |

### Build your own ISO or VM image

Use [tacklebox](https://github.com/tuna-os/tacklebox) to build ISOs:

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

## 🔐 Container Registry Authentication

Images are published on GitHub Container Registry (GHCR). To pull images with `bootc` or `podman`:

```bash
# Authenticate to GHCR (requires a GitHub personal access token with read:packages scope)
echo "$GITHUB_TOKEN" | podman login ghcr.io -u YOUR_USERNAME --password-stdin

# Or use the GitHub CLI
gh auth token | podman login ghcr.io -u YOUR_USERNAME --password-stdin
```

See [GitHub Container Registry docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) for more details.

## 🧪 Current Status

> **Note:** These images are in active development. Yellowfin and Albacore are the most mature variants. Bonito (Fedora) still needs work.

## Contributing

Contributions welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) for:
- Development environment setup
- Build workflow and pre-commit checklist
- Pull request guidelines
- Architecture overview

## 🤝 Community & Support

- 🐛 **Report Issues:** [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [m] **Chat**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)

Related Communities:
- 🎮 **Discord:** [Universal Blue Community](https://discord.gg/WEu6BdFEtp)
- 💬 **AlmaLinux Atomic SIG:** [AlmaLinux Atomic SIG](https://chat.almalinux.org/almalinux/channels/sigatomic)

## 📚 Documentation

### Project Docs
- [Contributor Guide](CONTRIBUTING.md) — how to set up, build, and contribute
- [Agent Guide](docs/AGENT_GUIDE.md) — complete architecture and contributor reference
- [Build Pipeline](docs/build-pipeline.md) — CI/CD workflow overview
- [Testing Guide](docs/TESTING.md) — ISO end-to-end test harness
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

This repository and many of the [tuna-os](https://github.com/tuna-os) repositories are developed and maintained using **[Hive](https://github.com/hanthor/hive)** — an AI-driven development platform orchestrated via [KubeStellar](https://kubestellar.io/).

Hive deploys a suite of specialized AI agents (guide, architect, sec-check, quality, ci-maintainer, strategist) onto a local Kubernetes cluster. These agents triage issues, implement fixes, review PRs, manage CI pipelines, and maintain documentation — all working autonomously through GitHub.

<img width="100" alt="Hive" src="https://avatars.githubusercontent.com/in/3942065" />

Every commit, PR, and issue in this repo benefits from multi-agent collaboration coordinated through Hive.

*Learn more: [hanthor/hive](https://github.com/hanthor/hive) | [KubeStellar](https://kubestellar.io/)*

---

*Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) Community*

*Licensed under [Apache 2.0](LICENSE)*

</div>
