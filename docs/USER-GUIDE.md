# TunaOS User Guide

Everything you need to run TunaOS day to day: picking an image, installing
it, staying updated, rolling back, and getting apps — plus what our quality
labels actually promise you.

## Is TunaOS for you?

TunaOS is for people who want their operating system to behave like firmware:
updated automatically, rolled back trivially, and otherwise invisible. Apps
come from Flathub and Homebrew; development happens in containers; the OS
itself is a signed image we build, test, and publish nightly.

TunaOS stands on the shoulders of the
[Universal Blue](https://universal-blue.org/) family, and we would rather
point you at their excellent documentation than re-explain what we share:

| If you are… | Read alongside this guide |
| :--- | :--- |
| new to image-based Linux, or a GNOME user | [Bluefin docs](https://docs.projectbluefin.io) — the model, apps, day-2 admin |
| a KDE Plasma user | [Aurora docs](https://docs.getaurora.dev) — the KDE workstation experience |
| here to game | [Bazzite](https://bazzite.gg) — the family's gaming specialist (see §8) |
| a Niri user | [Zirconium](https://github.com/zirconium-dev/zirconium) — literally the stack we ship |
| a developer | [Bluefin DX docs](https://docs.projectbluefin.io/bluefin-dx) — devcontainers, Podman, pet containers (see §9) |

What TunaOS adds to the family is *choice of base*: the same desktop
experience on Enterprise Linux, Fedora, Debian, Ubuntu, Arch, openSUSE, or
Gentoo — where Bluefin, Aurora, and Bazzite are Fedora-based, TunaOS lets you
pick the foundation and keep the experience.

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
- **You don't install packages onto the base.** Apps come from Flatpak,
  Homebrew, or containers (§7). Changing the base OS means switching to a
  different image — which is cheap and reversible (§6).

If you have used Silverblue, Bluefin, Aurora, or Bazzite, you already know
this model. If not, Bluefin's
[introduction](https://docs.projectbluefin.io/introduction) explains the
philosophy better than we could.

## 2. Choosing your image

A TunaOS image is named `<variant>:<desktop>[-hardware]`.

### The variant — which base OS

| Variant | Base OS | Cadence & character |
| :--- | :--- | :--- |
| 🐠 **yellowfin** | AlmaLinux Kitten 10 | Enterprise base, slightly fresher than Albacore |
| 🐟 **albacore** | AlmaLinux 10 (RHEL-compatible) | The long-stability pick |
| 🍣 **skipjack** | CentOS Stream 10 | Upstream of RHEL, rolling-ish enterprise |
| 🎣 **bonito** | Fedora 44 | Fedora cadence — closest cousin to Bluefin/Aurora |
| 🐉 **bonito-rawhide** | Fedora Rawhide | Fedora's dev branch; expect breakage |
| 🐡 **flounder** | Debian 13 (Trixie) | Debian stable |
| ☢️ **flounder-sid** | Debian Sid | Debian unstable |
| 🐟 **grouper** | Ubuntu 26.04 | Ubuntu LTS-next |
| 🐟 **gurnard** | Ubuntu 24.04 + Pantheon | Experimental |
| 🚀 **marlin** | Arch Linux | Rolling |
| 🦈 **sailfin** | openSUSE Tumbleweed | Rolling |
| 🌈 **guppy** | Gentoo | Binary-package Gentoo, the adventurous pick |
| 🐦 **hummingbird** | Fedora Hummingbird | Experimental next-gen Fedora base |
| 🎏 **wahoo** | Fedora ELN | Experimental EL11 preview — what c11s/Kitten 11 will be like, months early. **No H.264/H.265**: ELN ships no working video decoder, so this is a testing lane, not a daily driver |
| 🔒 **redfin** | RHEL 10 | Local-build only (EULA) — see [rhel-setup.md](rhel-setup.md) |

### The desktop — `gnome`, `kde`, `cosmic`, `niri`, `xfce`

All desktops are first-class across bases (where the base can support them).
`base` is the no-desktop server-style image. Our Niri desktop is the
[Zirconium](https://github.com/zirconium-dev/zirconium) stack, built from the
same pinned source Zirconium ships on Fedora.

### The hardware suffix — optional

- `-hwe` — Hardware Enablement kernel for newer hardware
- `-nvidia` — NVIDIA drivers + CUDA (via [Universal Blue akmods](https://github.com/ublue-os/akmods), the same driver packaging Bazzite and Aurora use)
- `-nvidia-hwe` — both
- `-asahi` — Apple Silicon (select variants; see [ASAHI-HARDWARE-TIERS.md](ASAHI-HARDWARE-TIERS.md))

So `ghcr.io/tuna-os/albacore:kde-nvidia` is AlmaLinux 10 + KDE Plasma +
NVIDIA. The live per-cell status of every combination is in the
[README build matrix](../README.md) and [MATRIX-STATUS.md](MATRIX-STATUS.md).

### What "green" promises — read this once

Historically, a green cell meant "the image built and was published". We have
deliberately raised that bar: [GREEN-CRITERIA.md](GREEN-CRITERIA.md) defines
what full green means — builds, desktop present, boots, installs, updates
and rolls back, honest about omissions — and the README reports **built**
and **composite green** separately. A variant can be built-green and still
carry known gaps on the harder criteria; the scoreboard tells you which.
Pick yellowfin/albacore gnome or kde if you want the most-proven cells
today.

## 3. Installing

### Option A — ISO installer

Download an ISO for your variant/desktop (where published), write it to a
USB stick, boot it, and follow the installer. TunaOS installers run
[fisherman](https://github.com/projectbluefin/fisherman) under a GUI
frontend and support encrypted installs (§10).

### Option B — from any existing bootc system

Already on Bluefin, Aurora, Bazzite, Silverblue-bootc, or another TunaOS
image? Switch in place:

```bash
sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
sudo systemctl reboot
```

Your home directory and local data are untouched; the OS beneath you is
replaced atomically. Switching back is the same command with the old image.

### Option C — VM / cloud

Every image can be turned into a disk image locally:

```bash
git clone https://github.com/tuna-os/tunaOS.git && cd tunaOS
just qcow2 ghcr.io/tuna-os/bonito:kde     # produces bonito.qcow2
just run-qcow2 bonito kde                  # boots it under QEMU
```

### Option D — from Windows (wootc)

Moving from Windows 10/11? You can install TunaOS directly without flashing a USB drive using **[wootc](https://github.com/tuna-os/wootc)** (the Windows bootc installer). Download `tunaos-installer.exe` from [wootc releases](https://github.com/tuna-os/wootc/releases), select your desktop, and reboot. See [MIGRATION.md](../MIGRATION.md#from-windows-wootc) for full details.

## 4. Day-2 administration

This section mirrors Bluefin's
[administration guide](https://docs.projectbluefin.io/administration) — same
model, same habits — with TunaOS specifics called out.

### Updates

Updates arrive as new image builds from nightly CI, and are applied
automatically by **[uupd](https://github.com/ublue-os/uupd)** (the Universal
Blue updater, running on a systemd timer) — the same updater Bluefin and
Aurora use. It also keeps Flatpaks and Homebrew current. Staged updates
activate on the next reboot; nothing changes under a running system.

Update manually any time:

```bash
sudo bootc upgrade          # fetch + stage the newest image
sudo bootc status           # what you're on, what's staged
```

(We deliberately ship uupd instead of bootc's own
`bootc-fetch-apply-updates.timer`, which is masked in our images — one
updater, not two.)

### ujust — the task runner

Like the rest of the family, TunaOS ships **`ujust`**: curated just recipes
for common admin tasks. Run `ujust` with no arguments to list what's
available on your image.

### Tailscale, out of the box

`tailscaled` is enabled by default, same as Aurora: `sudo tailscale up` and
you're on your tailnet. Prefer another VPN? `sudo tailscale down` and use
NetworkManager as usual.

### Changing system defaults

bootc keeps the OS in an immutable `/usr`; **your** configuration lives in
`/etc` and wins over the image's defaults (shipped under `/usr/etc`). Drop
overrides into `/etc` — systemd units, dconf keys, sysctl — and they persist
across updates. `sudo ostree admin config-diff` shows everything you've
changed from stock.

### Why there is no package layering

Bluefin documents `rpm-ostree` layering as a last resort; TunaOS images are
**bootc-native across seven different package ecosystems**, so host-level
layering isn't offered at all. The intended paths are, in order: Flatpak →
Homebrew → distrobox/toolbox container → build your own image
([ROLL_YOUR_OWN.md](ROLL_YOUR_OWN.md) — the equivalent of Universal Blue's
custom-image story). That last option is the escape hatch that makes the
first three acceptable.

You can still run `dnf` inside a toolbox, and some images do ship a
repository definition under `/etc/yum.repos.d` — hummingbird carries the
tunaOS package repository, for instance. What they do **not** ship is the
repositories that existed only while the image was being built: those are
bind-mounted directories that are gone by the time you boot, and a
definition left pointing at one would fail every `dnf` transaction rather
than sit there harmlessly. The build removes them at the end of the desktop
install, so every repository an image ships is one a running system can
actually reach.

## 5. Rollback

One command, or pick the previous entry in the boot menu:

```bash
sudo bootc rollback
sudo systemctl reboot
```

An image-based OS makes "get back to a working system" a one-liner. Use it
first, debug second.

## 6. Rebasing — desktop, hardware, or entire base

Rebasing is the same `bootc switch` from §3. Common moves:

```bash
# same base, different desktop
sudo bootc switch ghcr.io/tuna-os/albacore:niri

# same everything, add NVIDIA
sudo bootc switch ghcr.io/tuna-os/albacore:kde-nvidia

# hop bases entirely (Alma → Fedora), keeping your data
sudo bootc switch ghcr.io/tuna-os/bonito:kde
```

Cross-base hops are supported by the model but are the least-tested path —
treat them as an experiment, and know `bootc rollback` is always there.

## 7. Apps: Flatpak, Homebrew, containers

- **Graphical apps** come from **Flathub**, enabled out of the box — via
  your desktop's software center (GNOME Software / KDE Discover) or
  `flatpak install flathub org.mozilla.firefox`.
- **CLI tools** come from **Homebrew**, baked into the image the same way
  Bluefin does it (`ghcr.io/ublue-os/brew`): `brew install ripgrep`.
- **Everything else** works great in containers: `distrobox` / `toolbox`
  give you a mutable Fedora/Ubuntu/Arch/anything userland with your home
  directory mounted — the family's answer to "but I need `apt install`".

## 8. Gaming

For serious gaming on this family of operating systems, the honest answer
is: **[Bazzite](https://bazzite.gg)** is the specialist — Steam Gaming Mode,
Proton tuning, HDR/VRR, handheld support — and if gaming is your primary
use, run Bazzite. On TunaOS, the basics work the family way: install Steam,
Lutris, or Heroic from Flathub, and NVIDIA users pick a `-nvidia` image
(§2). Bazzite's documentation on Proton, controllers, and per-game tuning
largely applies to any Flathub Steam install, and is the best reference for
those topics on our Fedora-based variants too.

## 9. For developers

The [Bluefin DX](https://docs.projectbluefin.io/bluefin-dx) philosophy —
develop in containers, keep the host boring — is the intended workflow on
TunaOS as well:

- **Devcontainers** in VS Code or JetBrains against Podman (preinstalled on
  all variants).
- **Pet containers** via distrobox for a long-lived mutable shell.
- **Kubernetes/cloud tooling** via Homebrew (`brew install kubectl helm k9s …`).

TunaOS does not currently ship a separate `-dx` image tier; the container
tooling above is present in the standard images. For hacking on TunaOS
itself, see the [Developer Guide](DEVELOPER-GUIDE.md).

## 10. Disk encryption and secure boot

- Installers support **LUKS full-disk encryption** with optional **TPM2
  auto-unlock**; a recovery key is generated and shown during install. Keep
  it. Details: [LUKS-TPM.md](LUKS-TPM.md).
- Secure Boot state and expectations per variant: [SECURE-BOOT.md](SECURE-BOOT.md).

## 11. Verifying what you run

Every published image is signed with cosign and carries an attested SBOM:

```bash
image=ghcr.io/tuna-os/yellowfin:gnome
digest=$(skopeo inspect "docker://${image}" | jq -r .Digest)
ref="ghcr.io/tuna-os/yellowfin@${digest}"

cosign verify "${ref}" \
  --certificate-identity \
    "https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-image.yml@refs/heads/main" \
  --certificate-oidc-issuer \
    "https://token.actions.githubusercontent.com"
```

More in [VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md).

## 12. When something goes wrong

1. **Roll back first** (`sudo bootc rollback` + reboot), then debug.
2. Check your cell in [MATRIX-STATUS.md](MATRIX-STATUS.md): if the axis
   that bit you is ❌ or ⬜ there, it's known territory.
3. Search [issues](https://github.com/tuna-os/tunaOS/issues); file one with
   `bootc status` output and your image ref if it's new.
4. Ask in [Discord](https://discord.gg/MXSTqB8Nv).

**FAQ, in brief.** *Can I install .rpm/.deb files?* Not on the host — use
distrobox, or build your own image. *Do I lose data on rebase?* No; `/home`
and `/etc` persist. *How current are images?* Built nightly; uupd applies
them automatically. *Is my exact combination tested?* Check the composite
scoreboard — we publish exactly what is and isn't proven, per cell.

## 13. Further reading

- [Bluefin documentation](https://docs.projectbluefin.io) — the model,
  administration, DX; most of it applies here
- [Aurora documentation](https://docs.getaurora.dev) — the KDE sibling
- [Bazzite](https://bazzite.gg) — gaming on this family
- [Zirconium](https://github.com/zirconium-dev/zirconium) — our Niri stack
- [bootc documentation](https://bootc-dev.github.io/bootc/) — the
  underlying technology
- [DEVELOPER-GUIDE.md](DEVELOPER-GUIDE.md) — how all of this is built
