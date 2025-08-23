
# Note: Builds are failing as I update the core logic. I'll focus on this after finalizing the build for Bluefin LTS. 

<div align="center">

# 🐟 TunaOS
### *A Collection of Atomic Desktop Operating Systems*

*Specialized forks of [Bluefin LTS](https://github.com/ublue-os/bluefin-lts) for different use cases*

---

[![License](https://img.shields.io/github/license/hanthor/tunaOS?style=for-the-badge)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/hanthor/tunaOS?style=for-the-badge)](https://github.com/hanthor/tunaOS/stargazers)
[![Issues](https://img.shields.io/github/issues/hanthor/tunaOS?style=for-the-badge)](https://github.com/hanthor/tunaOS/issues)

</div>

## 🚀 About TunaOS

TunaOS is a curated collection of **Atomic desktop operating systems** that are forks of Bluefin, built on modern container technology. This is an exploration of the flexibilty of Bootc and a hope that some people believe in the Enterprise Linux Desktop. The plan it to provide a stable experience with up-to-date GNOME and modern tooling. 

## 🐠 Available Variants

### 🐠 Yellowfin
[![Build Status](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml/badge.svg?branch=yellowfin)](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml)

**Base:** [AlmaLinux Kitten 10](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#container-images)
**Image:** `ghcr.io/tuna-os/yellowfin:latest`  
**Branch:** [yellowfin](https://github.com/hanthor/tunaOS/tree/yellowfin)


The closest to upstream Bluefin LTS experience with enhanced capabilities:
- ✨ **x86_64/v2** microarchitecture support for older CPUs (pre-2013)
- 🖥️ **SPICE support** for qemu/libvirt virtualization
- 🔄 **Compatible with upstream LTS** because it's based on CentOS

---

### 🐟 Albacore
[![Build Status](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml/badge.svg?branch=albacore)](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml)

**Base:** AlmaLinux 10.0
**Image:** `ghcr.io/tuna-os/albacore:latest`  
**Branch:** [albacore](https://github.com/hanthor/tunaOS/tree/albacore)

Stable enterprise-grade desktop experience built on AlmaLinux foundation.

#### 🖥️ Albacore Server
[![Build Status](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml/badge.svg?branch=albacore-server)](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml)

**Image:** `ghcr.io/tuna-os/albacore-server:latest`  
**Branch:** [albacore-server](https://github.com/hanthor/tunaOS/tree/albacore-server)

Server-optimized variant with:
- 🚫 **No GNOME on Boot** (display manager disabled)
- 💻 **Virtualization Host** capabilities included
- 🏢 **Perfect for** server deployments and virtualization hosts

---

### 🎣 Bluefin Tuna
[![Build Status](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml/badge.svg?branch=bluefin-tuna)](https://github.com/hanthor/tunaOS/actions/workflows/build-regular.yml)

**Base:** Fedora 42
**Image:** `ghcr.io/tuna-os/bluefin-tuna:latest`  
**Branch:** [bluefin-tuna](https://github.com/hanthor/tunaOS/tree/bluefin-tuna)

Cutting-edge experience with Bluefin LTS tooling ported to the latest Fedora release.

## 📋 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | x86_64, ARM64 | x86_64/v2 or better, ARM64 |
| **RAM** | 4 GB | 8 GB+ |
| **Storage** | 20 GB | 50 GB+ |
| **Architecture** | AMD64, ARM64 | AMD64/v2, ARM64 |

## 🛠️ Installation

### Container Runtime
```bash
podman pull ghcr.io/hanthor/tunaos:yellowfin  # or your preferred variant
```

### Bootable Image
Use [bootc-image-builder](https://github.com/osbuild/bootc-image-builder) to create installation media:

run the [build-iso.sh](https://github.com/Tuna-OS/tunaOS/blob/main/build-iso.sh) script in this repo or download the script and run it to use bootc-image-builder to make an ISO:

```bash
curl https://raw.githubusercontent.com/Tuna-OS/tunaOS/refs/heads/main/build-iso.sh -o build-iso.sh
chmod +x build-iso.sh 
./build-iso.sh ghcr.io/tuna-os/yellowfin-dx:latest
```

## 🧪 Current Status

> **Note:** These images are currently in active development. The maintainer is daily-driving `yellowfin` and planning to deploy `albacore-server` as a Proxmox replacement.

## 🤝 Community & Support

We'd love to hear from you! Whether you're using these images or just curious:

- 🐛 **Report Issues:** [GitHub Issues](https://github.com/hanthor/tunaOS/issues)
- 🎮 **Discord:** [Universal Blue Community](https://discord.gg/WEu6BdFEtp)
- 💬 **Chat with AlmaLinux:** [AlmaLinux Atomic SIG](https://chat.almalinux.org/almalinux/channels/sigatomic)

## 📚 Documentation

- [AlmaLinux Kitten 10 Differences](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#how-is-almalinux-os-kitten-different-from-centos-stream)
- [Bluefin LTS Documentation](https://github.com/ublue-os/bluefin-lts)
- [Project Bluefin Documentation](https://docs.projectbluefin.io)
- [Universal Blue](https://universal-blue.org/)

---

<div align="center">

**Made by James in his free time**

*Licensed under [Apache 2.0](LICENSE)*

</div>
