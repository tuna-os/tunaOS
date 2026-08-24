# Bonito (Fedora-based) Fedora 45 Beta Testing Call & Community Guide

**Target Audience**: Fedora Atomic / bootc Community, r/Fedora, r/FedoraAtomic, Fedora Discourse Testers  
**Tracks**: [#1742](https://github.com/tuna-os/tunaOS/issues/1742) (Fedora 45 beta tester call — active); supersedes closed [#1609](https://github.com/tuna-os/tunaOS/issues/1609)  
**Supports**: [#1137](https://github.com/tuna-os/tunaOS/issues/1137) (Fedora Magazine Guest Post Pitch) & [#1166](https://github.com/tuna-os/tunaOS/issues/1166) (Q4 Release Calendar)

---

## 🏔️ Background: Bonito on the Fedora Release Cycle

TunaOS's **Bonito** variant brings a container-native, image-mode bootc desktop
experience to Fedora users.

**Read this before testing: TunaOS does not ship a Fedora 45 image.** Checked
2026-08-14 against the build config and the upstream base registry:

| what you can install | Fedora stream |
|---|---|
| `bonito:<flavor>` | **Fedora 44** — `build-config.yml` pins `quay.io/fedora/fedora-bootc:44` |
| `bonito:<flavor>-rawhide` | **Rawhide** — which is now Fedora **46** development, since `fedora-bootc` publishes both `45` and `46` |

So neither image is Fedora 45: one is a release behind it, the other a release
ahead. That is deliberate rather than an oversight —
[FEDORA-BASE-POLICY.md](../FEDORA-BASE-POLICY.md) sequences Fedora 45 base work to
begin **after** Bonito (Fedora 44) reaches GA
([#272](https://github.com/tuna-os/tunaOS/issues/272)), specifically so the
project is not carrying two incomplete Fedora bases at once.

This matters for what the call can honestly ask for. Describing these images as
"Bonito on Fedora 45" would mislead testers about what they are running, and the
results feed the Fedora Magazine pitch
([#1137](https://github.com/tuna-os/tunaOS/issues/1137)) — F44 and Rawhide
findings labelled as Fedora 45 data is the kind of thing an editor checks.

**What this call actually is**, and is worth doing on its own terms: an
invitation to Fedora users, who are already testing during the Fedora 45 cycle,
to try an image-mode bootc desktop built on the Fedora they can run today. Test
Rawhide if you want to see where the base is heading; test the stable image if
you want something that should just work. When a Fedora 45 base lands, this
document gets a fourth row and a re-announcement.

## 🚦 Variant health gate (2026-08-15)

**Do not announce a stream that is red.** The call's promise to testers is that
the image boots and is worth their time; pointing a community call at a broken
stream is the same credibility failure the fact-check discipline
([#1667](https://github.com/tuna-os/tunaOS/issues/1667)) is meant to prevent.

Checked 2026-08-15 against the nightly matrix:

| Stream | Status 2026-08-15 | Tracking |
|---|---|---|
| `bonito` (F44, stable) | 🟢 builds green | — |
| `bonito-rawhide` (F46 dev) | 🔴 **base fails on both amd64 + arm64** — 14 cells red | [#1752](https://github.com/tuna-os/tunaOS/issues/1752) |

**Consequences for the call:**

1. The Rawhide test row below is **not publishable until #1752 is resolved** —
   a tester pointed at `gnome-rawhide` today hits a broken base, and an
   "it's broken" report is not useful beta data.
2. Re-check the matrix before any announcement (Fedora 45 beta ~late Aug, per
   [#1742](https://github.com/tuna-os/tunaOS/issues/1742)); announce the Rawhide
   arm of the call only when it is green, or lead with the stable F44 image and
   mark Rawhide as "coming back online".
3. When a Fedora 45 base lands, update the stream table above **and** re-verify
   this gate — a new base can introduce its own red cells.

---

## 📋 What to Test (Bonito Test Matrix)

We are calling for community testing across three core Bonito configurations:

| Image / Target | Desktop / Architecture | Key Test Focus |
|---|---|---|
| `ghcr.io/tuna-os/bonito:gnome` (F44) | GNOME / x86_64, arm64 | Boot, Wayland session, Flatpak preinstall, Extensions |
| `ghcr.io/tuna-os/bonito:kde` (F44) | KDE Plasma / x86_64, arm64 | Wayland login, SDDM/plasmalogin, Dolphin, Konsole |
| `ghcr.io/tuna-os/bonito:niri` (F44) | Niri (Zirconium) / x86_64 | Scrollable tiling compositor, Wayland portals, Greetd |
| `ghcr.io/tuna-os/bonito:gnome-rawhide` (F46 dev) | GNOME / x86_64, arm64 | The same checks, on the newest base — this is where breakage shows up first |

All four tags were verified published in GHCR on 2026-08-14 — but see the
[health gate above](#-variant-health-gate-2026-08-15): the `bonito-rawhide`
base has been red on both architectures since the 08-15 nightly
([#1752](https://github.com/tuna-os/tunaOS/issues/1752)), so **the Rawhide row
is not currently announceable**. The Fedora stream is stated per row on
purpose: a tester who reports "works on Fedora 45" about an image that is not
Fedora 45 has produced data nobody can use.

---

## 🧪 Testing Workflow & Verification Checklist

### 1. Zero-Friction QEMU/KVM VM Trial (20 Minutes)
Test without touching physical disks:
```bash
# Builds a qcow2 for the flavor and boots it (web console URL is printed).
scripts/run-vm.sh demo bonito gnome
```

> `just vm-run` was in an earlier draft of this guide and is not a recipe in
> the Justfile — the first command a tester runs has to be one that exists.
> `just qcow2 bonito gnome` builds the disk image without booting it.
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
- [Matrix Status — which variant×desktop cells are verified](MATRIX-STATUS.md)
- [ADOPTERS.md Ecosystem & Production Registry](../ADOPTERS.md)
