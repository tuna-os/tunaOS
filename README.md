
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

</div>

## 🚀 About TunaOS

TunaOS is a curated collection of **bootc-based desktop operating systems** built on modern container technology. The goal is to bring a modern desktop experience to Enterprise Linux — stable, immutable, and up-to-date. Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) community.

### Features

- **Modern Desktops**: GNOME, KDE Plasma, COSMIC, and Niri — your choice, on Enterprise Linux
- **Latest GNOME**: Don't get stuck on a 3-year-old GNOME. We backport the latest desktop features to the Enterprise Desktop
- **Homebrew**: Baked into the image — all your CLI apps and fonts are just a `brew` command away
- **Flathub by Default**: Full Flathub access out of the box — get any Flatpak available on the net
- **HWE Option**: Hardware Enablement kernel for newer hardware support
- **GDX Option**: NVIDIA drivers and CUDA for graphics and AI workflows

## 🐠 Images

<div align="center">

<img width="328" height="318" alt="1000016351" src="https://github.com/user-attachments/assets/759fc093-baf0-4959-900a-5e9c2098f745" />
</div>

### Desktops

Each variant ships multiple desktop environments:

| Tag suffix | Desktop |
|---|---|
| `gnome` | GNOME (stable) |
| `gnome50` | GNOME 50 (latest) |
| `kde` | KDE Plasma |
| `cosmic` | COSMIC Desktop |
| `niri` | Niri (tiling Wayland compositor) |

### Hardware Variants

Append to any desktop tag:

| Suffix | Description |
|---|---|
| *(none)* | Standard build |
| `-hwe` | Hardware Enablement — newer kernel stack |
| `-gdx` | NVIDIA drivers + CUDA |
| `-gdx-hwe` | GDX on HWE kernel |

Example: `ghcr.io/tuna-os/yellowfin:gnome-hwe`, `ghcr.io/tuna-os/albacore:kde-gdx`

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

### 🎣 Bonito (Fedora 43)

**Base:** Fedora 43 — cutting-edge Fedora on bootc

**Platforms:** x86_64, ARM64

```
ghcr.io/tuna-os/bonito:gnome
ghcr.io/tuna-os/bonito:kde
ghcr.io/tuna-os/bonito:niri
ghcr.io/tuna-os/bonito:cosmic
```

---

## 📋 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | x86_64, ARM64 | x86_64, ARM64 |
| **RAM** | 4 GB | 8 GB+ |
| **Storage** | 20 GB | 50 GB+ |

## 🛠️ Installation

### Use a pre-built ISO

ISOs are published every two weeks for `gnome` and `gnome-hwe` flavors of Yellowfin and Albacore:

| Variant | GNOME | GNOME (HWE) |
|---------|-------|-------------|
| **Albacore** | [albacore-gnome-latest.iso](https://download.tunaos.org/live-isos/albacore-gnome-latest.iso) | [albacore-gnome-hwe-latest.iso](https://download.tunaos.org/live-isos/albacore-gnome-hwe-latest.iso) |
| **Yellowfin** | [yellowfin-gnome-latest.iso](https://download.tunaos.org/live-isos/yellowfin-gnome-latest.iso) | [yellowfin-gnome-hwe-latest.iso](https://download.tunaos.org/live-isos/yellowfin-gnome-hwe-latest.iso) |

### Build your own ISO or VM image

Use [bootc-image-builder](https://github.com/osbuild/bootc-image-builder) directly:

```bash
# ISO
sudo podman run --rm -it --privileged \
  -v /var/lib/containers/storage:/var/lib/containers/storage \
  ghcr.io/osbuild/bootc-image-builder:latest \
  --type iso \
  ghcr.io/tuna-os/yellowfin:gnome

# QCOW2 (VM image)
sudo podman run --rm -it --privileged \
  -v /var/lib/containers/storage:/var/lib/containers/storage \
  ghcr.io/osbuild/bootc-image-builder:latest \
  --type qcow2 \
  ghcr.io/tuna-os/yellowfin:gnome
```

### Switch an existing system

If you're already running a compatible bootc system:

```bash
sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
```

## 🧪 Current Status

> **Note:** These images are in active development. Yellowfin and Albacore are the most mature variants. Bonito (Fedora) still needs work.

## Contributing

PRs welcome! The goal is a great modern desktop on Enterprise Linux.

## 🤝 Community & Support

- 🐛 **Report Issues:** [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [m] **Chat**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)

Related Communities:
- 🎮 **Discord:** [Universal Blue Community](https://discord.gg/WEu6BdFEtp)
- 💬 **AlmaLinux Atomic SIG:** [AlmaLinux Atomic SIG](https://chat.almalinux.org/almalinux/channels/sigatomic)

## 📚 Documentation

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

*Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) Community*

*Licensed under [Apache 2.0](LICENSE)*

</div>
