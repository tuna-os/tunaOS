# TunaOS User Guide

Everything you need to run TunaOS day to day: picking an image, installing it,
staying updated, rolling back, and getting apps — plus what our quality labels
actually promise you.

TunaOS stands on the shoulders of the [Universal Blue](https://universal-blue.org/)
family: [Bluefin](https://projectbluefin.io) (GNOME),
[Aurora](https://getaurora.dev) (KDE), and
[Zirconium](https://github.com/zirconium-dev/zirconium) (Niri). Their
documentation applies to TunaOS more often than not, because we ship the same
image-based model, the same Homebrew and Flathub integration, and — for Niri —
literally the same desktop stack. When this guide is thin somewhere, the
[Bluefin documentation](https://docs.projectbluefin.io) is the best second
read. What TunaOS adds is *choice of base*: the same desktop experience on
Enterprise Linux, Fedora, Debian, Ubuntu, Arch, openSUSE, or Gentoo.

---

## 1. What kind of OS this is

TunaOS images are **bootc-based**: the operating system is delivered as a
container image, and your installed system atomically updates to each new
image. That means:

- **Updates are atomic.** An update either fully applies or doesn't happen.
  There is no half-updated system to debug.
- **Rollback is built in.** The previous deployment stays on disk; one
  command (or one boot-menu pick) returns to it.
- **The OS is the same everywhere.** Your installation is bit-for-bit the
  image we test in CI, not a package soup that drifted from it.
- **You don't `dnf install` onto the base.** Apps come from Flatpak,
  Homebrew, or containers (see §6). Changing the base OS means switching to
  a different image — which is cheap and reversible.

If you have used Fedora Silverblue, Bluefin, or Aurora, you already know this
model. If not, Bluefin's
[introduction](https://docs.projectbluefin.io/introduction) explains the
philosophy well.

## 2. Choosing your image

A TunaOS image is named `<variant>:<desktop>[-hardware]`.

### The variant — which base OS

| Variant | Base OS | Cadence & character |
| :--- | :--- | :--- |
| 🐠 **yellowfin** | AlmaLinux Kitten 10 | Enterprise base, slightly fresher than Albacore |
| 🐟 **albacore** | AlmaLinux 10 (RHEL-compatible) | The long-stability pick |
| 🍣 **skipjack** | CentOS Stream 10 | Upstream of RHEL, rolling-ish enterprise |
| 🎣 **bonito** | Fedora 44 | Fedora cadence, broad hardware |
| 🐉 **bonito-rawhide** | Fedora Rawhide | Fedora's dev branch; expect breakage |
| 🐡 **flounder** | Debian 13 (Trixie) | Debian stable |
| ☢️ **flounder-sid** | Debian Sid | Debian unstable |
| 🐟 **grouper** | Ubuntu 26.04 | Ubuntu LTS-next |
| 🐟 **gurnard** | Ubuntu 24.04 + Pantheon | Experimental |
| 🚀 **marlin** | Arch Linux | Rolling |
| 🦈 **sailfin** | openSUSE Tumbleweed | Rolling |
| 🌈 **guppy** | Gentoo | Binary-package Gentoo, the adventurous pick |
| 🐦 **hummingbird** | Fedora Hummingbird | Experimental next-gen Fedora base |
| 🔒 **redfin** | RHEL 10 | Local-build only (EULA) — see [rhel-setup.md](rhel-setup.md) |

### The desktop — `gnome`, `kde`, `cosmic`, `niri`, `xfce`

All desktops are first-class across bases (where the base can support them).
`base` is the no-desktop server-style image. Our Niri desktop is the
[Zirconium](https://github.com/zirconium-dev/zirconium) stack, built from the
same source Zirconium ships on Fedora.

### The hardware suffix — optional

- `-hwe` — Hardware Enablement kernel for newer hardware
- `-nvidia` — NVIDIA drivers + CUDA (via [Universal Blue akmods](https://github.com/ublue-os/akmods))
- `-nvidia-hwe` — both
- `-asahi` — Apple Silicon (select variants; see [ASAHI-HARDWARE-TIERS.md](ASAHI-HARDWARE-TIERS.md))

So `ghcr.io/tuna-os/albacore:kde-nvidia` is AlmaLinux 10 + KDE Plasma +
NVIDIA. The full, live per-cell status of every combination is in the
[README build matrix](../README.md) and [MATRIX-STATUS.md](MATRIX-STATUS.md).

### What "green" promises — read this once

Historically, a green cell meant "the image built and was published". We have
deliberately raised that bar: [GREEN-CRITERIA.md](GREEN-CRITERIA.md) defines
what full green means — builds, desktop present, boots, installs, updates and
rolls back, honest about omissions — and the README now reports **built** and
**composite green** separately. A variant can be built-green and still carry
known gaps on the harder criteria; the scoreboard tells you which. Pick
yellowfin/albacore gnome or kde if you want the most-proven cells today.

## 3. Installing

### Option A — ISO installer

Download an ISO for your variant/desktop (where published), write it to a USB
stick, boot it, and follow the installer. TunaOS installers run
[fisherman](https://github.com/projectbluefin/fisherman) under a GUI frontend
and support encrypted installs (see §7).

### Option B — from any existing bootc system

Already on Bluefin, Aurora, Silverblue-bootc, or another TunaOS image? Switch
in place:

```bash
sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
sudo systemctl reboot
```

Your home directory and local data are untouched; the OS beneath you is
replaced atomically. Switching back is the same command with the old image.

### Option C — VM / cloud

Every image can be turned into a disk image locally:

```bash
git clone https://github.com/tuna-os/tunaOS && cd tunaOS
just qcow2 ghcr.io/tuna-os/bonito:kde     # produces bonito.qcow2
just run-qcow2 bonito kde                  # boots it under QEMU
```

## 4. Staying updated

Updates arrive as new image builds (nightly CI). Apply them with:

```bash
sudo bootc upgrade
```

or let the built-in automatic updater fetch and stage them; the update
activates on the next reboot. Nothing changes out from under a running
system.

Check what you're on and what's staged:

```bash
sudo bootc status
```

## 5. Rollback and rebasing

**Roll back** to the previous deployment — one command, or pick the previous
entry in the boot menu:

```bash
sudo bootc rollback
sudo systemctl reboot
```

**Rebase** to a different desktop, hardware tier, or even a different base —
it's the same `bootc switch` from §3. Common moves:

```bash
# same base, different desktop
sudo bootc switch ghcr.io/tuna-os/albacore:niri

# same everything, add NVIDIA
sudo bootc switch ghcr.io/tuna-os/albacore:kde-nvidia

# hop bases entirely (Alma -> Fedora), keeping your data
sudo bootc switch ghcr.io/tuna-os/bonito:kde
```

Cross-base hops are supported by the model but are the least-tested path —
treat them as an experiment, and know `bootc rollback` is always there.

## 6. Apps: Flatpak, Homebrew, containers

- **Graphical apps** come from **Flathub**, enabled out of the box:
  `flatpak install flathub org.mozilla.firefox` or use your desktop's
  software center.
- **CLI tools** come from **Homebrew**, baked into the image the same way
  Bluefin does it (`ghcr.io/ublue-os/brew`): `brew install ripgrep`.
- **Development environments** work great in containers: `distrobox` /
  `toolbox` give you a mutable Fedora/Ubuntu/anything userland with your
  home directory mounted. Bluefin's
  [devcontainer guidance](https://docs.projectbluefin.io) applies unchanged.

The one thing you *don't* do is layer packages onto the base with the host
package manager — the base is the image.

## 7. Disk encryption and secure boot

- Installers support **LUKS full-disk encryption** with optional **TPM2
  auto-unlock**; a recovery key is generated and shown during install. Keep
  it. Details: [LUKS-TPM.md](LUKS-TPM.md).
- Secure Boot state and expectations: [SECURE-BOOT.md](SECURE-BOOT.md).

## 8. Verifying what you run

Every published image is signed with cosign and carries an attested SBOM:

```bash
cosign verify ghcr.io/tuna-os/yellowfin:gnome \
  --certificate-identity-regexp 'github.com/tuna-os/tunaOS' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

More in [VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md).

## 9. When something goes wrong

1. **Roll back first** (`sudo bootc rollback` + reboot). An image-based OS
   makes "get back to a working system" a one-liner — use it, then debug.
2. Check your cell in [MATRIX-STATUS.md](MATRIX-STATUS.md): if the axis that
   bit you is ❌ or ⬜ there, it's known territory.
3. Search [issues](https://github.com/tuna-os/tunaOS/issues); file one with
   `bootc status` output and your image ref if it's new.
4. Ask in [Discord](https://discord.gg/MXSTqB8Nv).

## 10. Further reading

- [Bluefin documentation](https://docs.projectbluefin.io) — the model, apps,
  devcontainers; most of it applies here
- [Aurora](https://getaurora.dev) — the KDE sibling upstream
- [Zirconium](https://github.com/zirconium-dev/zirconium) — our Niri stack
- [bootc documentation](https://bootc-dev.github.io/bootc/) — the underlying
  technology
- [DEVELOPER-GUIDE.md](DEVELOPER-GUIDE.md) — how all of this is built
