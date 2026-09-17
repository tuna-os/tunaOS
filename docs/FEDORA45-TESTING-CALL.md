# Bonito (Fedora-based) Fedora 45 Beta Testing Call & Community Guide

**Target Audience**: Fedora Atomic / bootc Community, r/Fedora, r/FedoraAtomic, Fedora Discourse Testers.  
**Tracks**: [#1742](https://github.com/tuna-os/tunaOS/issues/1742) (Fedora 45 beta tester call — active); supersedes closed [#1609](https://github.com/tuna-os/tunaOS/issues/1609).  
**Supports**: [#1137](https://github.com/tuna-os/tunaOS/issues/1137) (Guest Post Pitch for Fedora Magazine) & [#1166](https://github.com/tuna-os/tunaOS/issues/1166) (Q4 Release Calendar)

---

## 🏔️ Background: Bonito on the Fedora Release Cycle

TunaOS's **Bonito** variant brings a container-native desktop experience to
Fedora users, in image mode and built on bootc.

**Read this before you test: TunaOS does not ship a Fedora 45 image.** Checked
2026-08-14 against the build config and the upstream base registry:

| what you can install | Fedora stream |
|---|---|
| `bonito:<flavor>` | **Fedora 44** — `build-config.yml` pins `quay.io/fedora/fedora-bootc:44` |
| `bonito:<flavor>-rawhide` | **Rawhide** — which is now Fedora **46** development, since `fedora-bootc` publishes both `45` and `46` |

So neither image is Fedora 45: one is a release behind it, the other a release
ahead. That is deliberate, not an oversight.
[FEDORA-BASE-POLICY.md](../FEDORA-BASE-POLICY.md) sequences Fedora 45 base work to
begin **after** Bonito (Fedora 44) reaches GA
([#272](https://github.com/tuna-os/tunaOS/issues/272)). The reason is specific:
the project must not carry two Fedora bases at once while both are incomplete.

This matters for what the call can honestly ask for. A description of these
images as "Bonito on Fedora 45" would mislead testers about what they run. The
results also feed the pitch to Fedora Magazine
([#1137](https://github.com/tuna-os/tunaOS/issues/1137)). F44 and Rawhide
findings labelled as Fedora 45 data is the kind of thing an editor checks.

**What this call is**: an invitation to Fedora users who already test during
the Fedora 45 cycle. It is worth doing on its own terms. They can try an
image-mode bootc desktop built on the Fedora they can run today. Test
Rawhide if you want to see where the base is heading. Test the stable image if
you want something that should work out of the box. When a Fedora 45 base
lands, this document gets a fourth row and a re-announcement.

## 🚦 Variant health gate (2026-08-15)

**Do not announce a red stream.** The call's promise to testers is that
the image boots and is worth their time. A community call that points at a
broken stream is the same credibility failure the fact-check discipline
([#1667](https://github.com/tuna-os/tunaOS/issues/1667)) is meant to prevent.

Checked 2026-08-15 against the nightly matrix:

| Stream | Status 2026-08-15 | Tracking |
|---|---|---|
| `bonito` (F44, stable) | 🟢 builds green | — |
| `bonito-rawhide` (F46 dev) | 🔴 **base fails on both amd64 + arm64** — 14 cells red | [#1752](https://github.com/tuna-os/tunaOS/issues/1752) |

**Consequences for the call:**

1. **Do not publish the Rawhide test row below** until someone resolves #1752.
   A tester pointed at `gnome-rawhide` today hits a broken base, and an
   "it's broken" report is not useful beta data.
2. Re-check the matrix before any announcement (Fedora 45 beta ~late Aug, per
   [#1742](https://github.com/tuna-os/tunaOS/issues/1742)). Announce the Rawhide
   arm of the call only when the matrix shows green. If it does not, lead with
   the stable F44 image and mark Rawhide as "coming back online".
3. When a Fedora 45 base lands, update the stream table above **and** re-verify
   this gate. A new base can introduce its own red cells.

---

## 📋 What to Test (Bonito Test Matrix)

We ask the community for tests on three core configurations of Bonito:

| Image / Target | Desktop / Architecture | Key Test Focus |
|---|---|---|
| `ghcr.io/tuna-os/bonito:gnome` (F44) | GNOME / x86_64, arm64 | Boot, Wayland session, Flatpak preinstall, Extensions |
| `ghcr.io/tuna-os/bonito:kde` (F44) | KDE Plasma / x86_64, arm64 | Wayland login, SDDM/plasmalogin, Dolphin, Konsole |
| `ghcr.io/tuna-os/bonito:niri` (F44) | Niri (Zirconium) / x86_64 | Scrollable tiling compositor, Wayland portals, Greetd |
| `ghcr.io/tuna-os/bonito:gnome-rawhide` (F46 dev) | GNOME / x86_64, arm64 | The same checks, on the newest base — this is where breakage shows up first |

We verified on 2026-08-14 that GHCR publishes all four tags. But see the
[health gate above](#-variant-health-gate-2026-08-15): the `bonito-rawhide`
base shows red on both architectures since the 08-15 nightly
([#1752](https://github.com/tuna-os/tunaOS/issues/1752)). **Therefore we cannot
announce the Rawhide row now.** We state the Fedora stream per row on purpose.
A tester who reports "works on Fedora 45" about an image that is not
Fedora 45 produces data nobody can use.

---

## 🧪 Testing Workflow & Verification Checklist

### 1. Zero-Friction QEMU/KVM VM Trial (20 Minutes)
Test, and do not touch physical disks:
```bash
# Builds a qcow2 for the flavor and boots it (web console URL is printed).
scripts/run-vm.sh demo bonito gnome
```

> `just vm-run` was in an earlier draft of this guide and is not a recipe in
> the Justfile. The first command a tester runs has to be one that exists.
> `just qcow2 bonito gnome` builds the disk image but does not boot it.
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
- [ ] **First Boot**: System reaches the graphical screen for login (GDM/SDDM/Greetd).
- [ ] **Desktop Contract**: Desktop session launches in a smooth way, with audio (Pipewire) and portals (`xdg-desktop-portal`).
- [ ] **Container Image Updates**: `sudo bootc update` runs and stages atomic updates of layers successfully.
- [ ] **Atomic Rollback**: `sudo bootc rollback` safely returns the system to the prior deployment.
- [ ] **Hardware Acceleration**: the GPU renders graphics (`glxinfo` / `vulkaninfo` / `nvidia-smi` where applicable).

---

## 📢 Community Engagement & Feedback Channels

- **GitHub Discussion**: Post test logs, hardware specs, and feedback to the [Beta Test Thread for Bonito on Fedora 45](https://github.com/tuna-os/tunaOS/discussions).
- **Public Community Outlets**: Share your test experiences on `r/Fedora`, `r/FedoraAtomic`, and Fedora Discourse. Respect the promotion guidelines of each channel.
- **Bug Reports**: File issue reports tagged `bonito` and `verification-failed` on `tuna-os/tunaOS`.

---

## 🔗 Related Resources
- [Guest Post Pitch for Fedora Magazine](FEDORA-MAGAZINE-PITCH.md)
- [Decision Guide for Variant Selection](USER-GUIDE.md#2-choosing-your-image)
- [Matrix Status — which variant×desktop cells have verification](MATRIX-STATUS.md)
- [ADOPTERS.md Ecosystem & Production Registry](../ADOPTERS.md)
