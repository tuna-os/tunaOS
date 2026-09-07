# GNOME 51.0 Release-Week Content & Packaging Hook

> Status: **draft** — for maintainer review before GNOME 51 release week (~September 2026).
> Tracking issue: [#1334](https://github.com/tuna-os/tunaOS/issues/1334) (GNOME 51.0 release-week content — packaging hook).
> Prepared: 2026-08-29. Target window: GNOME 51.0 release week (~Sep 12–19, 2026).

---

## Strategic Context

Enterprise Linux users (AlmaLinux 10, CentOS Stream 10, RHEL 10) typically wait years for major GNOME desktop environment upgrades. TunaOS bridges this gap by packaging current GNOME releases—specifically **GNOME 51.0**—on top of Enterprise Linux bases on day one, delivered as atomic, rollback-capable `bootc` container images.

### The Packaging Hook
- **Tier-based Mock Builds**: TunaOS packages the complete GNOME 51 desktop stack (`mutter`, `gnome-shell`, `gtk4`, `libadwaita`, `nautilus`, `gdm`, `ptyxis`, `orca`, and core shell extensions) through an automated, mock-based build pipeline.
- **Native RPM Repository on Cloudflare R2**: Packages are built in-house and distributed directly from the TunaOS Cloudflare R2 RPM repository rather than unmaintained third-party PPAs or stale COPR repositories (aligning with org package sourcing policy #1319).
- **Atomic Image Assembly**: The resulting RPMs are layered into bootable OCI container images (`Yellowfin:gnome`, `Albacore:gnome`, `Skipjack:gnome`) and cryptographically signed with Sigstore/cosign keyless signing.

---

## Ready-to-Publish Content Drafts

### 1. Blog Post Draft (`tunaos.org/blog`)

**Title**: `GNOME 51 on Enterprise Linux: Day-One Desktop Modernity with TunaOS bootc`
**Date**: `2026-09-12`
**Author**: `TunaOS Team`

```markdown
# GNOME 51 on Enterprise Linux: Day-One Desktop Modernity with TunaOS bootc

Today marks the official release of GNOME 51, bringing major architectural improvements, refined Adwaita styling, performance gains in Mutter, and next-generation Wayland enhancements to the Linux desktop.

Traditionally, running the latest GNOME meant choosing between rapid-release upstream distributions (like Fedora or Arch) or accepting years-old desktop packages on an Enterprise Linux (EL) LTS base.

With **TunaOS**, you no longer have to compromise.

Starting today, TunaOS delivers **GNOME 51 on Enterprise Linux 10** (AlmaLinux 10 and CentOS Stream 10 bases) as atomic, bootable container images.

### How it works: Enterprise Base + Modern Desktop Stack

TunaOS packages the complete GNOME 51 user space natively against EL10:
- **Core Shell & Compositor**: GNOME Shell 51, Mutter 51 with variable refresh rate (VRR) and fractional scaling improvements.
- **Modern App Toolkit**: GTK 4.x and Libadwaita updates backported without breaking base system glibc or core runtime compatibility.
- **Cloudflare R2 Native RPMs**: In compliance with our package sourcing policy, all backported RPMs are built in clean mock environments and hosted on high-availability Cloudflare R2 storage.
- **Transactional bootc Deployment**: Upgrading is atomic. Run `bootc upgrade` to transition your workstation to GNOME 51. If any regression occurs, `bootc rollback` returns you to your previous working snapshot in seconds.

### Trying GNOME 51 on TunaOS

To run GNOME 51 on TunaOS:
```bash
# Pull and switch to the GNOME 51 image on Albacore (EL10)
sudo bootc switch ghcr.io/tuna-os/albacore:gnome

# Or test in a local container / VM
podman run -d --name tuna-gnome-test ghcr.io/tuna-os/albacore:gnome
```

Downloadable x86_64 ISOs are available immediately at [tunaos.org/download](https://tunaos.org/download).
```

---

### 2. Reddit / Lemmy Announcement Draft

**Target Communities**: r/gnome, r/linux, r/AlmaLinux, r/CentOS, Lemmy `!linux@lemmy.ml`

**Title**: `TunaOS brings GNOME 51 to Enterprise Linux 10 on release day — bootc images with atomic rollback`

**Body**:
> GNOME 51 is out today, and we've packaged the full desktop stack for Enterprise Linux 10 (AlmaLinux 10 and CentOS Stream 10) in TunaOS.
>
> If you love Enterprise Linux stability for the base system and kernel, but don't want to be locked into an outdated desktop environment for the next 5 years, this is built for you:
>
> - **Full GNOME 51 stack**: Shell, Mutter, GTK4/Libadwaita apps, Nautilus, Ptyxis, GDM.
> - **Atomic bootc updates**: Delivered as OCI container images. Updates are transactional and reversible (`bootc rollback`).
> - **Native package sourcing**: Built in-house via isolated mock pipelines and served from Cloudflare R2 (no abandoned COPRs).
> - **Multi-arch**: x86_64 and aarch64 container images published to GHCR.
>
> Download ISOs: https://tunaos.org/download
> Technical details & blog post: https://tunaos.org/blog/2026/09/12/gnome-51-coming-to-tunaos
> Issue & discussion: https://github.com/tuna-os/tunaOS/issues/1334

---

### 3. GNOME Discourse / Planet GNOME Community Note

**Topic**: `Packaging GNOME 51 for Enterprise Linux via bootc containers`

> Hello GNOME community!
>
> Congratulations on the GNOME 51 release. The TunaOS project has published packaging and bootable container images enabling GNOME 51 on AlmaLinux 10 and CentOS Stream 10.
>
> Our goal is to make the latest GNOME innovations immediately accessible to workstation users in enterprise and research environments that require EL10 lifecycles. All packaging is maintained openly, built against EL10 sysroots, and tested across both x86_64 and aarch64.
>
> We welcome feedback from GNOME developers and packagers:
> - Repository: https://github.com/tuna-os/tunaOS
> - Discussion & Package Manifests: https://github.com/tuna-os/tunaOS/tree/main/manifests/desktops/gnome.yaml

---

## Distribution Checklist

- [ ] Verify GNOME 51 RPM build tiers green in CI
- [ ] Confirm R2 repository index generated and signed
- [ ] Verify `Yellowfin:gnome`, `Albacore:gnome`, and `Skipjack:gnome` container builds passing
- [ ] Publish blog post to `tunaos.org/blog`
- [ ] Post Reddit/Lemmy announcements (maintainer account)
- [ ] Post Fediverse toot (using Toot 2 from [FEDIVERSE-PLAYBOOK.md](FEDIVERSE-PLAYBOOK.md))
- [ ] Share on GNOME Discourse packaging forum
- [ ] Log referral deltas in [ADOPTION-METRICS.md](../ADOPTION-METRICS.md)
