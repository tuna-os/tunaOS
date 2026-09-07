# CachyOS Ecosystem Engagement & Marlin Variant Integration Guide

> Status: **draft** — for maintainer review. Do **not** post externally without
> maintainer sign-off (external community action; issue-first per outreach
> policy).  
> Tracking: [#1692](https://github.com/tuna-os/tunaOS/issues/1692).  
> Fact-checked 2026-08-30 against `README.md`, `ROADMAP.md`, and `Containerfile.arch`
> in `tuna-os/tunaOS` per the maintainer's press-claim guard ([#1667](https://github.com/tuna-os/tunaOS/issues/1667)).

---

## 1. Context & Technical Relationship

TunaOS's **Marlin** variant delivers an immutable, container-native (`bootc`) desktop built on an Arch Linux rolling base integrated with the **CachyOS repository and kernel overlay**.

Through the CachyOS package repositories, Marlin systems utilize performance-optimized packages (compiled with x86-64-v3/v4 micro-architecture optimizations) and run the high-performance **`linux-cachyos`** kernel featuring modern CPU schedulers (BORE / sched-ext).

### Recent Upstream & Container Hardening
The Marlin variant completed major initramfs and boot-pipeline hardening:
- **Single-kernel-tree initramfs rebuilds** ([#1640](https://github.com/tuna-os/tunaOS/issues/1640))
- **Stock kernel removal** in favor of generated initramfs for all cachyos-overlay kernels ([#1641](https://github.com/tuna-os/tunaOS/issues/1641))
- **Built-in boot driver acceptance** in initramfs parity check ([#1679](https://github.com/tuna-os/tunaOS/issues/1679), [#1689](https://github.com/tuna-os/tunaOS/issues/1689))
- **Kernel-tree guard implementation** ([#1690](https://github.com/tuna-os/tunaOS/issues/1690))

The technical narrative for Marlin is: **"CachyOS-grade performance with atomic bootc updates and instant rollback safety."**

---

## 2. Engagement Objectives & Channel Targets

- **Primary Channels:**
  - Reddit: `r/CachyOS`, `r/archlinux`
  - CachyOS Discord: `#general`, `#showcase`, `#development`
  - GitHub: Cross-linking issues between `tuna-os/tunaOS` and `CachyOS`
- **Goals:**
  - Introduce Marlin to performance enthusiasts who want CachyOS kernel/package speed without the fragility of unmanaged rolling updates.
  - Establish a collaborative feedback loop with the CachyOS developer community around OCI-based container packaging and initramfs handling.
  - Propose TunaOS Marlin as a reference immutable deployment option for CachyOS enthusiasts.

---

## 3. Community Post Draft: r/CachyOS & CachyOS Discord

**Post Title:** Marlin: An immutable, rollback-safe desktop built on CachyOS's kernel and package overlay

**Post Body:**

```markdown
Hey CachyOS community,

We wanted to share an open-source project that builds directly on top of the incredible work being done here: **TunaOS Marlin**.

### What is Marlin?
TunaOS is an image-based desktop distribution where the entire operating system is packaged and distributed as a bootable OCI container via `bootc`. 

The **Marlin** variant couples that containerized, atomic update model with the performance advantages of CachyOS:
- **Arch Base + CachyOS Overlay:** Marlin pulls directly from CachyOS's optimized x86-64-v3/v4 package repositories.
- **Linux-CachyOS Kernel:** Ships with the CachyOS performance kernel by default across all flavors.
- **Atomic Upgrades & Rollbacks:** System updates happen in a single transactional step via `bootc upgrade`. If an upstream package conflict or driver regression occurs, `bootc rollback` instantly reverts to your exact previous operational snapshot at boot time.

### Desktop Flavors
Marlin publishes `*-cachyos` image tags for:
- GNOME
- KDE Plasma
- COSMIC
- Niri
- XFCE
- Minimal Base

### Try Marlin via bootc:
```bash
# Switch to the Marlin GNOME CachyOS image:
bootc switch ghcr.io/tuna-os/marlin:gnome-cachyos
```

### Honest Status & Development
Marlin is currently in **Beta** for x86_64. We recently completed a sequence of kernel/initramfs hardening updates (single-kernel-tree initramfs generation and boot-driver parity checks).

We'd love for CachyOS power users and benchmarkers to test it out and share your thoughts!

- GitHub Repo: https://github.com/tuna-os/tunaOS
- Issue Tracker: https://github.com/tuna-os/tunaOS/issues
```

---

## 4. Fact-Checking & Engagement Guards (per #1667)

- **Marlin Lifecycle State:** Marlin is in **Beta** (x86_64 only). Do **not** describe Marlin as "fully GA" or "production enterprise ready."
- **NVIDIA Status:** Note any active NVIDIA overlay tracking items ([#1499](https://github.com/tuna-os/tunaOS/issues/1499)) transparently when users inquire about proprietary drivers.
- **No Endorsement Overclaim:** Clearly frame TunaOS Marlin as a downstream consumer of CachyOS open repositories. Do not state or imply that the CachyOS project officially endorses or maintains TunaOS.
- **Sign-Off & Tracking:** Await maintainer sign-off before publishing. Record thread links and community feedback in `docs/ADOPTION-OUTREACH-STATUS.md`.
