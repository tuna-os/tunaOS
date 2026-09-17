# Migration Guide — Moving to tunaOS

This guide helps you migrate to tunaOS from Windows or other Linux distributions.

## Overview

tunaOS is a collection of bootc-based Atomic desktop operating system images. It uses `bootc` for image-based updates and `rpm-ostree` for package layering (Yellowfin/Albacore variants) or native bootc tooling (Bonito/Skipjack).

⚠️ **Always back up your data before migrating.** Migration is a rebase operation — it changes your OS image. While reversible, data loss is possible if steps are incorrect.

---

## From Fedora Silverblue / Kinoite / Sericea

Fedora Atomic desktops use rpm-ostree natively. Migration to a tunaOS variant is a rebase operation. Yellowfin and Albacore are AlmaLinux-based; Skipjack is CentOS Stream 10; Bonito is Fedora 44 (see [ROADMAP.md](ROADMAP.md) for variant details).

### Step 1: Identify your target variant

| Current | Target tunaOS Variant | Base |
|---------|----------------------|------|
| Fedora Silverblue (GNOME) | Yellowfin GNOME | AlmaLinux Kitten 10 |
| Fedora Kinoite (KDE) | Yellowfin KDE | AlmaLinux Kitten 10 |
| Fedora Sericea (Sway) | Albacore COSMIC or Niri | AlmaLinux 10 |

### Step 2: Rebase

```bash
# Check current deployment
rpm-ostree status

# Rebase to tunaOS (example: Yellowfin GNOME)
sudo rpm-ostree rebase ostree-unverified-registry:ghcr.io/tuna-os/yellowfin:gnome

# Reboot into tunaOS
sudo systemctl reboot
```

### Step 3: Verify

```bash
# Confirm the new deployment
rpm-ostree status

# Check bootc status (if bootc-enabled variant)
bootc status
```

### Rollback

If something goes wrong:

```bash
# Rollback to previous deployment
sudo rpm-ostree rollback
sudo systemctl reboot
```

---

## From Universal Blue (Bluefin, Aurora, Bazzite)

Universal Blue images are Fedora-based. Migration to an EL-based tunaOS variant (Yellowfin/Albacore/Skipjack) is a rebase, but note:

- **Package layering differences**: Some layered packages may not be available in AlmaLinux repositories or may have different names.
- **Container tooling**: tunaOS uses `podman` and `docker` via the same container tools. `distrobox` is compatible.

### Migration Steps

```bash
# 1. List layered packages (save for reference)
rpm-ostree status | grep LayeredPackages

# 2. Rebase to tunaOS
sudo rpm-ostree rebase ostree-unverified-registry:ghcr.io/tuna-os/yellowfin:gnome

# 3. Reboot
sudo systemctl reboot

# 4. Re-apply layered packages as needed
# Note: package names may differ between Fedora and AlmaLinux
sudo rpm-ostree install <pkg1> <pkg2> ...
```

### From Bluefin (GNOME)

Bluefin users should target **Yellowfin GNOME** — the closest equivalent.

```bash
sudo rpm-ostree rebase ostree-unverified-registry:ghcr.io/tuna-os/yellowfin:gnome
```

### From Aurora (KDE)

Aurora users should target **Yellowfin KDE**.

```bash
sudo rpm-ostree rebase ostree-unverified-registry:ghcr.io/tuna-os/yellowfin:kde
```

### From Bazzite (gaming)

Bazzite users: note that tunaOS does not ship gaming-specific kernel tweaks or Steam pre-installed. You can layer these post-migration:

```bash
sudo rpm-ostree install steam-devices mangohud gamemode
```

---

## From Fedora Workstation (Traditional)

Fedora Workstation is a traditional (non-Atomic) distribution. Direct migration is not supported. Options:

1. **Fresh install**: Use a tunaOS ISO to install directly
2. **Container-based transition**: Export data, install tunaOS, restore from backup

Direct rebase from traditional Fedora to an Atomic image is not supported by rpm-ostree.

---

## From RHEL / CentOS / AlmaLinux (Traditional)

Traditional Enterprise Linux installations cannot be directly rebased to an Atomic image.

### Option 1: Fresh Install

Use a tunaOS ISO to perform a fresh installation.

### Option 2: Convert to bootc (Advanced)

If your system supports it, you can convert a traditional EL system to bootc. This is advanced and not recommended for production without testing.

```bash
# This is theoretical — verify with tunaOS documentation for current procedure
bootc switch ghcr.io/tuna-os/yellowfin:gnome
```

---

## From Other Atomic Desktops

### openSUSE MicroOS

MicroOS uses transactional-update, not rpm-ostree. Direct migration is not supported. Use a fresh install.

### Vanilla OS

Vanilla OS 2 (Orchid) uses ABRoot, not rpm-ostree. Direct migration is not supported.

### Endless OS

Endless OS uses OSTree but with a different deployment model. Migration is not tested or supported.

---

## From Windows (wootc)

If you are now running Windows (Windows 10 or 11), you can migrate to TunaOS directly using **[wootc](https://github.com/tuna-os/wootc)** without needing to burn a USB flash drive or repartition your drive in advance.

wootc is a Windows installer application for TunaOS:
- **No USB stick required**: Runs directly within Windows and prepares a bootable environment.
- **Safe alongside Windows**: Installs to a loop root disk (`root.disk`) on your existing drive while keeping Windows intact in the UEFI boot menu. A BitLocker-encrypted disk is not yet a supported path — that work is tracked as wootc#223 and is Q4 scope in [ROADMAP.md](ROADMAP.md) — so suspend BitLocker or back up your recovery key before you start.
- **Migration assistance**: Can import Wi-Fi networks, wallpaper, browser profiles, keyboard layouts, WSL configurations, and user documents.
- **Full TunaOS catalog**: Choose from GNOME, KDE Plasma, COSMIC, Niri, or XFCE editions across supported TunaOS bases.
- **Honest rollback / uninstall**: Uninstall cleanly from Windows Settings / Add or Remove Programs, leaving no residual partition state.

### Getting Started with wootc

1. Download the latest installer from the [wootc releases page](https://github.com/tuna-os/wootc/releases) (e.g. `tunaos-installer.exe`).
2. Run the installer in Windows with administrator privileges.
3. Select your desired TunaOS desktop environment and variant, configure username and password, and allocate disk space.
4. Reboot your system and select TunaOS from the boot menu to complete setup.

For detailed instructions, refer to the [wootc Getting Started Guide](https://github.com/tuna-os/wootc/blob/main/docs/getting-started.md).

---

## Post-Migration Checklist

After migrating to tunaOS, verify:

- [ ] Desktop environment starts correctly
- [ ] Network connectivity works
- [ ] Display / GPU drivers functional
- [ ] Audio working
- [ ] Flatpak applications run (Flathub is pre-configured)
- [ ] `bootc status` shows correct image
- [ ] Container workloads work (`podman run hello-world`)

### Enabling Flathub

tunaOS ships with Flathub pre-configured. If you need to re-add it:

```bash
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```

---

## Image changes that affect existing installs

### tunaOS removes `alarm` on Arch ARM (marlin, arm64)

The stock rootfs of Arch Linux ARM ships an `alarm` account at UID 1000, and
marlin's arm64 images carried it. These images no longer hold that account, so
a live ISO can place its own user at UID 1000.

After `bootc upgrade`:

- If you never edited `/etc/passwd`, the account goes away with the upgrade.
  Nothing else changes.
- If you added or edited a user, your `/etc/passwd` counts as local
  configuration and `alarm` stays. Run `userdel alarm` by hand to free the UID.
- Files under `/var/home/alarm` survive either way. Once the account goes, they
  show a bare UID and no name.

Nobody should log in as `alarm` on a tunaOS system. It is an artifact of the
base image, and `build-archlinuxarm-base.yml` keeps it for the base alone.

### marlin's arm64 images carry a kernel again (marlin, arm64)

Every marlin `linux-arm64` image published before this change holds no kernel.
Arch Linux ARM ships the kernel as `/boot/Image` alone, and the bootc layout
step cleared `/boot` without a copy in `/usr/lib/modules/<kver>/vmlinuz`, which
is where bootc reads it.

A `bootc upgrade` onto one of those images stages a deployment that cannot
boot. Only arm64 marlin is affected; x86_64 marlin and every other variant
always carried the kernel.

- **On a system that still boots:** upgrade to an image built after this
  change. No other action is needed.
- **On a system that stopped booting after an upgrade:** pick the previous
  entry in the boot menu, then run `sudo bootc rollback` to make it the
  default. Upgrade again once a newer image is available.

To confirm an image before you deploy it, check that the path exists:

```bash
sudo bootc image copy-to-storage
podman run --rm ghcr.io/tuna-os/marlin:gnome ls /usr/lib/modules/*/vmlinuz
```

---

## Known Limitations

1. **NVIDIA drivers**: nvidia variant recommended for NVIDIA hardware. See [ROADMAP.md](ROADMAP.md) for available variants and flavors.
2. **Secure Boot**: NVIDIA flavors need manual enrollment of the MOK key on first boot after migration; community bases don't support Secure Boot at all — see [docs/SECURE-BOOT.md](docs/SECURE-BOOT.md).
3. **Dual boot**: Not recommended or tested with tunaOS Atomic images.
4. **Fingerprint readers**: May need additional driver configuration.

---

## Getting Help

- **Issues**: [github.com/tuna-os/tunaOS/issues](https://github.com/tuna-os/tunaOS/issues)
- **Discussions**: [github.com/tuna-os/tunaOS/discussions](https://github.com/tuna-os/tunaOS/discussions)
- See [CONTRIBUTING.md](CONTRIBUTING.md) for development contributions.

---

*For variant-specific details, see [ROADMAP.md](ROADMAP.md) and the build/installation guides at [tunaos.org](https://tunaos.org).*
