# GNOME 51 Beta Testing Call & EL10 Backport Tier Testing Guide

> Status: **draft** — for maintainer review. Do **not** post externally without
> maintainer sign-off.  
> Tracking: [#1717](https://github.com/tuna-os/tunaOS/issues/1717), [#1334](https://github.com/tuna-os/tunaOS/issues/1334).  
> Fact-checked 2026-08-30 against `tuna-os/tunaos-packages` (17 build tiers) and
> `tuna-os/tunaOS` per the maintainer's press-claim guard ([#1667](https://github.com/tuna-os/tunaOS/issues/1667)).

---

## 1. Objective & Technical Opportunity

Enterprise Linux distributions (AlmaLinux 10, CentOS Stream 10, RHEL 10) provide extraordinary long-term platform stability, but their desktop environment stacks lag behind upstream releases. 

TunaOS bridges this gap through its dedicated automated RPM backport tier in [`tuna-os/tunaos-packages`](https://github.com/tuna-os/tunaos-packages) (comprising 17 build tiers), delivering the full modern **GNOME 51** desktop stack—including Mutter, GTK4, Libadwaita, Nautilus, GNOME Shell, GDM, and Orca—on top of an enterprise EL10 base.

The upstream GNOME 51 beta window provides a high-leverage testing window to validate backported RPM packages, uncover regressions in Wayland compositing and hardware acceleration, and refine TunaOS Albacore/Yellowfin images ahead of the final GNOME 51.0 release.

---

## 2. Target Testing Channels

- **Matrix:** `#tunaos:matrix.org`
- **GitHub Discussions:** `tuna-os/tunaOS` Discussions (Testing & Feedback category)
- **Discourse:** GNOME Discourse (Third-Party / Distribution Testing), AlmaLinux Community Discourse
- **Reddit / Lemmy:** `r/gnome`, `r/AlmaLinux`, `!gnome@lemmy.ml`

---

## 3. Testing Guide & Instructions for Users

### A. Deploying the GNOME 51 Beta Image
Users running TunaOS Albacore or Yellowfin can evaluate GNOME 51 beta in an isolated VM or on bare-metal hardware with instant rollback safety:

```bash
# 1. Switch to the Albacore GNOME 51 testing container image:
sudo bootc switch ghcr.io/tuna-os/albacore:gnome-next

# 2. Reboot into the new deployment:
sudo systemctl reboot
```

### B. Immediate Rollback Command
If any blocking display or boot issue occurs:
```bash
# Roll back to your previous working deployment:
sudo bootc rollback
sudo systemctl reboot
```
*(Alternatively, select the previous bootloader entry at the GRUB / systemd-boot menu).*

---

## 4. Beta Testing Checklist

Testers are encouraged to validate the following functional areas and record their findings:

| Category | Test Item | Verification Steps |
|---|---|---|
| **Display & Session** | Wayland Compositor (Mutter) | Verify native Wayland session starts under GDM without fallback to Xwayland for desktop shell. |
| **Scaling** | Fractional Scaling | Test 125%, 150%, and 175% UI scaling on HiDPI displays. |
| **Core Apps** | Nautilus (Files) | Test file copying, archive extraction, MTP device mounting, and search indexing. |
| **Theming & Style** | Libadwaita & Dark Mode | Verify system dark/light theme toggles apply cleanly across core apps. |
| **Sandboxed Apps** | Flatpak / Portal Integration | Verify XDG Desktop Portals (file picker, screen sharing, camera) work inside Flatpaks. |
| **Accessibility** | Orca Screen Reader | Verify screen reading feedback and speech dispatcher integration. |
| **Stability** | Crash / Coredump Logs | Check `coredumpctl list` and `journalctl -b -p err` for unhandled mutter/shell crashes. |

---

## 5. Bug Reporting & Triage Protocol

When reporting regressions:
1. **Packaging / Build Issues:** Open an issue in [`tuna-os/tunaos-packages`](https://github.com/tuna-os/tunaos-packages/issues) with the prefix `[gnome51-beta]`.
2. **OS / Image / Boot Issues:** Open an issue in [`tuna-os/tunaOS`](https://github.com/tuna-os/tunaOS/issues) with reproduction logs:
   ```bash
   bootc status
   rpm -qa | grep -E "mutter|gnome-shell|gtk4"
   journalctl -u gdm -b
   ```

---

## 6. Pre-Publishing Verification Checklist

- [ ] Confirm RPM repository tier metadata (`repo.tunaos.org/gnome51/10-stream`) is active and reachable.
- [ ] Confirm `ghcr.io/tuna-os/albacore:gnome-next` builds are green in CI.
- [ ] Cross-check upstream GNOME 51 release schedule dates before posting.
- [ ] Maintainer approval obtained prior to external announcement.
