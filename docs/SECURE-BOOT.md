# Secure Boot support by variant

Short version: **the Enterprise-Linux variants (Yellowfin, Albacore,
Skipjack, Redfin) boot under Secure Boot out of the box** because they
inherit the distro-signed shim and kernel from their bootc base images.
**Everything NVIDIA needs one manual key enrollment**, and the
**community-base variants (Marlin, Flounder, Grouper, Sailfin, Guppy) do
not support Secure Boot out of the box today**.

"Out of the box" means: install, reboot with Secure Boot enabled, and
everything works — no firmware settings changed, no keys enrolled.

## Status table

| Variant | Base | Secure Boot out of the box? | Notes |
|---|---|---|---|
| Yellowfin | AlmaLinux Kitten 10 | ✅ Yes (standard flavors) | Alma-signed shim + kernel from the bootc base |
| Albacore | AlmaLinux 10 | ✅ Yes (standard flavors) | Alma-signed shim + kernel |
| Skipjack | CentOS Stream 10 | ✅ Yes (standard flavors) | CentOS-signed shim + kernel |
| Redfin | RHEL 10 (local build) | ✅ Yes (standard flavors) | Red Hat-signed shim + kernel |
| Any `*-nvidia` flavor | EL base + ublue akmods | ⚠️ **No** — one-time key enrollment required | See [NVIDIA flavors](#nvidia-flavors) |
| Any `*-hwe` flavor | EL base | ✅ Yes, today | The HWE overlay currently keeps the signed base kernel; if it ever swaps kernels this becomes ⚠️ like NVIDIA |
| Marlin (+ CachyOS overlay) | Arch Linux | ❌ No | Unsigned kernel (stock Arch / CachyOS), no signed shim — disable Secure Boot |
| Flounder / Flounder Sid | Debian 13 / Sid | ❌ Not out of the box | The bootcified image does not wire Debian's signed shim/kernel path; untested under SB — disable Secure Boot |
| Grouper | Ubuntu 26.04 | ❌ Not out of the box | Same as Flounder: signed-boot chain not wired in the bootcification; untested |
| Sailfin | openSUSE Tumbleweed | ❌ Not out of the box | openSUSE signs its kernels, but the bootcified image's shim path is untested — assume unsupported |
| Guppy | Gentoo | ❌ No | Source-built unsigned kernels; no signing infrastructure |

## NVIDIA flavors

All `*-nvidia` flavors (every variant) install the NVIDIA open kernel
modules from Universal Blue's `akmods-nvidia-open` packages. Those
modules are signed with the **Universal Blue akmods MOK key**, not a key
your firmware trusts, so under Secure Boot the system boots but the
NVIDIA driver is blocked until you enroll the key once:

```bash
ujust enroll-secure-boot-key   # if available on your image
# or manually:
sudo mokutil --import /etc/pki/akmods/certs/akmods-ublue.der
```

Reboot, and in the blue MOK Manager screen choose *Enroll MOK* →
*Continue* and enter the password (`universalblue` for the Universal
Blue key). This is a one-time step per machine.

## Migrated systems

Migrating an existing install to TunaOS (see
[MIGRATION.md](../MIGRATION.md)) keeps your firmware state; the same
table applies, and NVIDIA flavors need the MOK enrollment on first boot
after migration.

## What "not out of the box" means practically

- **Marlin / Guppy**: disable Secure Boot in firmware. There is no
  supported signing path today.
- **Flounder / Grouper / Sailfin**: disable Secure Boot. These bases
  have distro signing upstream, so wiring shim + signed kernels through
  the bootcification is possible future work — tracked per-variant, not
  promised.
- If a variant table row here disagrees with what you observe on real
  hardware, that is a bug in this document — please file an issue.
