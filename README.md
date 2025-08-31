
<div align="center">
<picture>
  <source srcset="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.webp" type="image/webp">
  <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif" alt="🐟" width="128" height="128">
</picture>

## TunaOS
### *A Collection of Cloud-Native Enterprise Linux OS Images*

*Specialized forks of [Bluefin LTS](https://github.com/ublue-os/bluefin-lts) based on AlmaLinux 10, AlmaLinux Kitten 10, CentOS 10, and Fedora*

---

[![License](https://img.shields.io/github/license/tuna-os/tunaOS?style=for-the-badge)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/stargazers)
[![Issues](https://img.shields.io/github/issues/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/issues)

</div>

## 🚀 About TunaOS

TunaOS is a curated collection of **Bootc-based desktop operating systems** that are forks of Bluefin LTS, built on modern container technology. This is an exploration of the flexibilty of Bootc and a hope that some people believe in the Enterprise Linux Desktop. The plan is to provide a stable experience with up-to-date GNOME and modern tooling. 

### Features

- **Latest GNOME**: Don't get stuck on a 3-year-old GNOME. We try to backport the latest Desktop feature and bring them to the Enterprise Desktop
  - Currently we're shipping GNOME `48.3` while EL will be stuck on GNOME `47` for the foreseeable future
- **Anaconda WebUI & Live ISO**: (Pending; present upstream)
- **Homebrew**: We bake Homebrew into the image, so all your CLI apps (and fonts) are just a brew command away
- **Flathub by Default**: This is a no-brainer that isn't preset in our base images. Actually get all the Flatpaks thata generally available on the net. 

## 🐠 Images
<div align="center">

<img width="328" height="318" alt="1000016351" src="https://github.com/user-attachments/assets/759fc093-baf0-4959-900a-5e9c2098f745" />
</div>

We ship 3 versions, matching upstream:

- [**Regular**:](https://docs.projectbluefin.io/)
    - See Bluefin's excellent documentation for info 
- [**DX (Developer Experience)**](https://docs.projectbluefin.io/dx)
    - Adding libvirt, Docker, VSCode, etc. 
- [**GDX (Graphical Developer Experience)**](https://docs.projectbluefin.io/gdx)
    - Adding Nvidia drivers and CUDA. For Nvdia users/AI/VFX devs.


### 🐟 Albacore (AlmaLinux)

**Base:** [AlmaLinux 10.0](https://almalinux.org/blog/2025-05-27-welcoming-almalinux-10/)

**Image:** `ghcr.io/tuna-os/albacore:latest` 

**DX:** `ghcr.io/tuna-os/albacore-dx:latest` 

**GDX:** `ghcr.io/tuna-os/albacore-gdx:latest` 


Stable enterprise-grade desktop experience built on AlmaLinux foundation.
- ✨ **x86_64/v2** microarchitecture support for older CPUs (pre-2013)
- 🖥️ **SPICE support** for qemu/libvirt virtualization

---
### 🐠 Yellowfin (AlmaLinux Kitten)

**Base:** [AlmaLinux Kitten 10](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#container-images)

**Image:** `ghcr.io/tuna-os/yellowfin:latest`  

**DX:** `ghcr.io/tuna-os/yellowfin-dx:latest`  

**GDX:** `ghcr.io/tuna-os/yellowfin-gdx:latest`  


The closest to upstream Bluefin LTS experience with enhanced capabilities:
- ✨ **x86_64/v2** microarchitecture support for older CPUs (pre-2013)
- 🖥️ **SPICE support** for qemu/libvirt virtualization
- 🔄 **Compatible with upstream LTS** because Kitten is based on CentOS

---
>[!NOTE]
> Bonito is still needing some work to get into a functional state
### 🎣 Bonito (Fedora)

**Base:** Fedora 42

**Image:** `ghcr.io/tuna-os/bonito:latest`  

Cutting-edge experience with Bluefin LTS tooling ported to the latest Fedora release.

---
### 🍣 Skipjack (CentOS)

**Base:**  CentOS 10

**Image:** `ghcr.io/tuna-os/skipjack:latest`  

---
## 📋 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | x86_64, ARM64 | x86_64, ARM64 |
| **RAM** | 4 GB | 8 GB+ |
| **Storage** | 20 GB | 50 GB+ |

## 🛠️ Installation

### Build-your-own ISO or VM image
run the [build-iso.sh](https://github.com/Tuna-OS/tunaOS/blob/main/build-iso.sh) script in this repo or download the script and run it to use bootc-image-builder to make an ISO:
```bash
curl https://raw.githubusercontent.com/Tuna-OS/tunaOS/refs/heads/main/build-iso.sh \
-o build-bootc.sh
chmod +x build-bootc.sh

# Now you can make a ISO for Albacore
sudo ./build-bootc.sh iso ghcr.io/tuna-os/albacore:latest

# Or build yellowfin-dx
sudo ./build-bootc.sh iso ghcr.io/tuna-os/yellowfin-dx:latest

# Or make a VM image
sudo ./build-bootc.sh qcow2 ghcr.io/tuna-os/yellowfin-dx:latest

# default username/password for VMs is "centos" / "centos"
# you can edit this in the script

```

## 🧪 Current Status

> **Note:** These images are currently in active development. I'm daily-driving `yellowfin` and maintaining the upstream Bluefin LTS

## Contributing

PRs welcome! The goal is to match the feature set of Bluefin LTS and Bluefin. 

## 🤝 Community & Support

We'd love to hear from you! Whether you're using these images or just curious:

- 🐛 **Report Issues:** [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
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

*Made by James in his free time*

*Powered by [Bootc](https://github.com/bootc-dev/bootc)*

*Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) Community*

*Licensed under [Apache 2.0](LICENSE)*

</div>
