# Bonito (Fedora-based) Fedora 45 Beta Testing Call & Community Guide

**Target Audience**: Fedora Atomic / bootc Community, r/Fedora, r/FedoraAtomic, Fedora Discourse Testers  
**Tracks**: [#1609](https://github.com/tuna-os/tunaOS/issues/1609) (Fedora 45 Beta testing call — Bonito variant)  
**Supports**: [#1137](https://github.com/tuna-os/tunaOS/issues/1137) (Fedora Magazine Guest Post Pitch) & [#1166](https://github.com/tuna-os/tunaOS/issues/1166) (Q4 Release Calendar)

---

## 🏔️ Background: Bonito on the Fedora Release Cycle

TunaOS's **Bonito** variant brings a container-native, image-mode bootc desktop experience to Fedora users. As the Fedora 45 release cycle advances (Beta ~September 2026, GA October 2026), testing Bonito across diverse hardware architectures and desktop environments gives Fedora testers an immutable desktop trial path while producing real community validation data.

---

## 📋 What to Test (Bonito Test Matrix)

We are calling for community testing across three core Bonito configurations:

| Image / Target | Desktop / Architecture | Key Test Focus |
|---|---|---|
| `ghcr.io/tuna-os/bonito:gnome` | GNOME / x86_64, arm64 | Boot, Wayland session, Flatpak preinstall, Extensions |
| `ghcr.io/tuna-os/bonito:kde` | KDE Plasma / x86_64, arm64 | Wayland login, SDDM/plasmalogin, Dolphin, Konsole |
| `ghcr.io/tuna-os/bonito:niri` | Niri (Zirconium) / x86_64 | Scrollable tiling compositor, Wayland portals, Greetd |

---

## 🧪 Testing Workflow & Verification Checklist

### 1. Zero-Friction QEMU/KVM VM Trial (20 Minutes)
Test without touching physical disks:
```bash
just vm-run bonito gnome
```
Or run directly via QEMU:
```bash
qemu-system-x86_64 -m 4096 -smp 4 \
  -drive file=tunaos-bonito-gnome.qcow2,format=qcow2 \
  -enable-kvm -cpu host -net nic -net user
```

### 2. Physical / Bare-Metal Testing (`bootc switch`)
On an existing Fedora Silverblue / Kinoite / bootc system:
```bash
sudo bootc switch ghcr.io/tuna-os/bonito:gnome
sudo systemctl reboot
```

### 3. Verification Checklist for Testers
- [ ] **First Boot**: System reaches graphical login screen (GDM/SDDM/Greetd).
- [ ] **Desktop Contract**: Desktop session launches smoothly with audio (Pipewire) and portals (`xdg-desktop-portal`).
- [ ] **Container Image Updates**: Running `sudo bootc update` successfully staging atomic layer updates.
- [ ] **Atomic Rollback**: Executing `sudo bootc rollback` safely returns to the prior deployment.
- [ ] **Hardware Acceleration**: GPU rendering active (`glxinfo` / `vulkaninfo` / `nvidia-smi` where applicable).

---

## 📢 Community Engagement & Feedback Channels

- **GitHub Discussion**: Post test logs, hardware specs, and feedback to the [Bonito Fedora 45 Beta Testing Thread](https://github.com/tuna-os/tunaOS/discussions).
- **Public Community Outlets**: Share testing experiences on `r/Fedora`, `r/FedoraAtomic`, and Fedora Discourse (respecting channel promotion guidelines).
- **Bug Reporting**: File issue reports tagged `bonito` and `verification-failed` on `tuna-os/tunaOS`.

---

## 🔗 Related Resources
- [Fedora Magazine Guest Post Pitch](FEDORA-MAGAZINE-PITCH.md)
- [Variant Selection Decision Guide](choosing-a-variant.md)
- [ADOPTERS.md Ecosystem & Production Registry](../ADOPTERS.md)
