> [!IMPORTANT]
>Builds are failing as I update the core logic. I'll focus on this after finalizing the build for Bluefin LTS. 

<div align="center">
<picture>
  <source srcset="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.webp" type="image/webp">
  <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif" alt="🐟" width="128" height="128">
</picture>

## TunaOS
### *A Collection of Cloud-Native Enterprise Linux OS Images*

*Specialized forks of [Bluefin LTS](https://github.com/ublue-os/bluefin-lts) based on AlmaLinux 10, AlmaLinux Kitten 10, CentOS 10, and Fedora*

---

[![License](https://img.shields.io/github/license/hanthor/tunaOS?style=for-the-badge)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/hanthor/tunaOS?style=for-the-badge)](https://github.com/hanthor/tunaOS/stargazers)
[![Issues](https://img.shields.io/github/issues/hanthor/tunaOS?style=for-the-badge)](https://github.com/hanthor/tunaOS/issues)

</div>

## 🚀 About TunaOS

TunaOS is a curated collection of **Atomic desktop operating systems** that are forks of Bluefin, built on modern container technology. This is an exploration of the flexibilty of Bootc and a hope that some people believe in the Enterprise Linux Desktop. The plan it to provide a stable experience with up-to-date GNOME and modern tooling. 

## 🐠 Available Variants

<img width="328" height="318" alt="1000016351" src="https://github.com/user-attachments/assets/759fc093-baf0-4959-900a-5e9c2098f745" />



### 🐟 Albacore

**Base:** AlmaLinux 10.0

**Image:** `ghcr.io/tuna-os/albacore:latest`  

Stable enterprise-grade desktop experience built on AlmaLinux foundation.

---
### 🐠 Yellowfin

**Base:** [AlmaLinux Kitten 10](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#container-images)

**Image:** `ghcr.io/tuna-os/yellowfin:latest`  


The closest to upstream Bluefin LTS experience with enhanced capabilities:
- ✨ **x86_64/v2** microarchitecture support for older CPUs (pre-2013)
- 🖥️ **SPICE support** for qemu/libvirt virtualization
- 🔄 **Compatible with upstream LTS** because it's based on CentOS

---

### 🎣 Bluefin Tuna

**Base:** Fedora 42
**Image:** `ghcr.io/tuna-os/bluefin-tuna:latest`  
**Branch:** [bluefin-tuna](https://github.com/hanthor/tunaOS/tree/bluefin-tuna)

Cutting-edge experience with Bluefin LTS tooling ported to the latest Fedora release.

## 📋 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | x86_64, ARM64 | x86_64, ARM64 |
| **RAM** | 4 GB | 8 GB+ |
| **Storage** | 20 GB | 50 GB+ |

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
chmod +x build-bootc.sh
sudo ./build-bootc.sh iso ghcr.io/tuna-os/albacore:latest
sudo ./build-bootc.sh iso ghcr.io/tuna-os/yellowfin-dx:latest

# Or make a VM image
sudo ./build-bootc.sh qcow2 ghcr.io/tuna-os/yellowfin-dx:latest

```

## 🧪 Current Status

> **Note:** These images are currently in active development. I'm daily-driving `yellowfin` and maintaining the upstream Bluefin LTS

## 🤝 Community & Support

We'd love to hear from you! Whether you're using these images or just curious:

- 🐛 **Report Issues:** [GitHub Issues](https://github.com/hanthor/tunaOS/issues)
- [m] **Chat**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia) 

Related Communities: 
- 🎮 **Discord:** [Universal Blue Community](https://discord.gg/WEu6BdFEtp)
- 💬 **AlmaLinux Atomic SIG:** [AlmaLinux Atomic SIG](https://chat.almalinux.org/almalinux/channels/sigatomic)

## 📚 Documentation

- [AlmaLinux Kitten 10 Differences](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#how-is-almalinux-os-kitten-different-from-centos-stream)
- [Bluefin LTS Documentation](https://github.com/ublue-os/bluefin-lts)
- [Project Bluefin Documentation](https://docs.projectbluefin.io)
- [Universal Blue](https://universal-blue.org/)

---

<div align="center">

**Made by James in his free time**
**Powered by [Bootc](https://github.com/bootc-dev/bootc)**
**Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) Community
*Licensed under [Apache 2.0](LICENSE)*

</div>
