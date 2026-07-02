# Modern Enterprise Linux Desktops with TunaOS

**Date**: 2026-06-27  
**Author**: TunaOS Community

---

Enterprise Linux has long been the go-to choice for servers: stable, secure, and supported for a decade. But what about the desktop?

For years, the answer was "use Fedora" or "deal with stale GNOME on RHEL." But with the rise of [bootc](https://github.com/bootc-dev/bootc) — container-native operating systems — that trade-off no longer exists.

Enter **TunaOS**: bootc-based Enterprise Linux desktops that combine the stability of AlmaLinux 10 with modern GNOME, KDE, COSMIC, and Niri desktops.

## What is TunaOS?

TunaOS is a collection of OCI-based desktop operating system images. Think of it like Docker for your OS — your entire system is a container image that you can rebase, roll back, and update atomically.

```bash
# Switch from Fedora Silverblue to TunaOS
sudo bootc switch --enforce-container-sigpolicy ghcr.io/tuna-os/yellowfin:gnome
sudo systemctl reboot
```

That's it. One command and your Enterprise Linux desktop is online.

## Why Enterprise Linux for Desktops?

| | Traditional EL Desktop | TunaOS |
|---|---|---|
| **Desktop freshness** | Stuck on 3-year-old GNOME | GNOME 50, KDE Plasma 6, COSMIC |
| **Updates** | `dnf upgrade` (risky) | Atomic rebase (instant rollback) |
| **Developer tools** | Manual setup | Homebrew baked in, DX edition |
| **Apps** | Limited repos | Flathub out of the box |
| **GPU support** | Manual NVIDIA setup | GDX edition with CUDA |

## Variants for Every Use Case

TunaOS offers four base variants, each targeting a different audience:

| Variant | Base | Best for |
|---|---|---|
| **Albacore** 🐟 | AlmaLinux 10 | Stable enterprise desktops |
| **Yellowfin** 🐠 | AlmaLinux Kitten 10 | Developers and early adopters |
| **Skipjack** 🍣 | CentOS Stream 10 | Upstream testing |
| **Bonito** 🎣 | Fedora 44 | Bleeding-edge experimentation |

Each variant comes in multiple desktop flavors: GNOME, KDE Plasma, COSMIC (Rust-based from System76), and Niri (scrollable tiling compositor).

## The Developer Experience

One of the biggest pain points with Enterprise Linux desktops has always been developer tooling. TunaOS fixes this:

- **Homebrew** is pre-installed — `brew install` anything
- **Flathub** is enabled out of the box — VS Code, JetBrains, Slack, all available
- **DX Edition** adds libvirt, Docker, and dev tools
- **NVIDIA Edition** includes CUDA for AI/ML workloads

```bash
# Install your tools
brew install gh just kind kubectl
flatpak install flathub com.visualstudio.code
```

## Migration is Easy

If you're already running Fedora Silverblue, Kinoite, or any rpm-ostree based desktop, migration is a single command:

```bash
sudo rpm-ostree rebase ostree-unverified-registry:ghcr.io/tuna-os/albacore:gnome
sudo systemctl reboot
```

Rollback is just as easy — pick the previous deployment from the bootloader.

See the full [Migration Guide](MIGRATION.md) for details.

## Getting Started

1. Check [system requirements](https://tunaos.org/docs/system-requirements)
2. Download an ISO from [tunaos.org](https://tunaos.org)
3. Install and reboot
4. Join the community on [Matrix](https://matrix.to/#/%23tunaos:reilly.asia)

## Join Us

TunaOS is an open-source community project. Whether you're running it in production, testing on a spare laptop, or contributing code — we'd love to have you.

- **Code**: [github.com/tuna-os/tunaOS](https://github.com/tuna-os/tunaOS)
- **Chat**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)
- **Docs**: [tunaos.org](https://tunaos.org)

If your organization uses TunaOS, please add yourself to [ADOPTERS.md](ADOPTERS.md) — it helps others see who's using the project.

---

*Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) community. Built on [AlmaLinux](https://almalinux.org), [Fedora](https://fedoraproject.org), and [CentOS](https://centos.org).*
