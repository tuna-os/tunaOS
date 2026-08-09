# Disk encryption & TPM2 auto-unlock

TunaOS installs (via fisherman) can encrypt the root filesystem with LUKS2.
You choose a **passphrase** during install, and TPM2 auto-unlock — no
passphrase prompt at boot — is enrolled automatically shortly after.

## Why TPM enrollment happens on first boot (not during the install)

TPM2 auto-unlock works by *sealing* the unlock key to the machine's measured
boot state (PCR **7** = Secure Boot state). That measurement only exists once
the **real installed system** boots — an installer running from the live ISO
measures a *different* PCR 7, so enrolling at install time seals against the
wrong state and the disk never unlocks afterward. This is the same model
Universal Blue (`ublue-os-luks`), Bazzite, and Fedora Silverblue use, and why
`bootc install` doesn't do it either ([bootc#421](https://github.com/bootc-dev/bootc/issues/421)).

So: **the installer sets a passphrase and stages a one-time enrollment for the
next boot; the first boot of your installed system enrolls the TPM against its
own real PCR 7 and removes the staged key** — no action needed from you. This
is a `ConditionFirstBoot` oneshot ([fisherman#48](https://github.com/tuna-os/fisherman/pull/48)),
fixing an earlier version that enrolled at install time and never actually
unsealed on the installed system (tunaOS#679, tunaOS#680).

**First boot after install still shows the passphrase prompt once** — TPM2
isn't enrolled yet at that point, so the passphrase is still required. Every
boot after that should be prompt-free.

## Re-enrolling manually

Enrollment can also be triggered by hand — useful if you disabled it, or need
to re-seal after a firmware/Secure Boot change invalidates the old seal:

```sh
ujust enable-luks-tpm2          # TPM only
ujust enable-luks-tpm2 --pin    # TPM + a PIN you set
```

(or `sudo tunaos-luks-tpm2-enroll`). This path seals to PCRs **7+14** (Secure
Boot state + MokList/shim — a stricter set than the automatic first-boot
enrollment's PCR 7 alone) and prompts interactively for your current
passphrase. To revert either kind of enrollment: `ujust disable-luks-tpm2`.

> **Keep your passphrase regardless.** Updating firmware, toggling Secure
> Boot, or re-enrolling MOK keys changes PCR 7/14 — the TPM then refuses to
> unseal and you fall back to the passphrase. That's the security trade-off,
> by design.

## Variant support matrix

TPM2 auto-unlock needs the systemd `tpm2-tss` dracut module in the
initramfs — which in turn needs a TPM2 userspace (`tpm2-tools` or
equivalent) present when the image is built, since `dracut-install`
refuses to package a module whose binaries don't exist — plus a working
`/dev/tpmrm0` on the machine at boot. Two of those three are knowable
**statically**, from what each base's package list and dracut config give
the initramfs, without booting anything; only the third (does it actually
unseal at runtime) needs the E2E boot. The columns below say which is
which:

| Variant | Base | Encrypted install (passphrase) | TPM2 userspace in initramfs | TPM2 auto-unlock | Notes |
|---------|------|-------------------------------|------------------------------|-------------------|-------|
| yellowfin | AlmaLinux Kitten 10 | ✅ (fisherman) | ✅ (RPM/dracut-config.sh probe) | _pending E2E_ | |
| skipjack | CentOS Stream 10 | ✅ | ✅ (RPM/dracut-config.sh probe) | _pending E2E_ | |
| albacore | AlmaLinux 10 | ✅ | ✅ (RPM/dracut-config.sh probe) | _pending E2E_ | |
| bonito | Fedora 44 | ✅ | ✅ (RPM/dracut-config.sh probe) | _pending E2E_ | |
| bonito-rawhide | Fedora Rawhide | ✅ | ✅ (RPM/dracut-config.sh probe) | _pending E2E_ | same Containerfile.el10 path as bonito |
| hummingbird | Fedora Hummingbird | ✅ | ✅ (RPM/dracut-config.sh probe) | _pending E2E_ | same Containerfile.el10 path as bonito |
| sailfin | openSUSE Tumbleweed | ✅ | ❌ **not built** | ❌ **not possible today** | `Containerfile.opensuse` omits `tpm2-tss`/`pcsc` from every dracut invocation unconditionally — no TPM2 userspace package is installed, so the module can never make it into the initramfs regardless of enrollment. tunaOS#714 |
| flounder | Debian 13 Trixie | ✅ | ✅ (`tpm2-tools` installed explicitly) | _pending E2E_ | |
| flounder-sid | Debian Sid | ✅ | ✅ (`tpm2-tools` installed explicitly) | _pending E2E_ | same `Containerfile.debian` path as flounder |
| grouper | Ubuntu 26.04 | ✅ | ✅ (`tpm2-tools` installed explicitly) | _pending E2E_ | composefs/systemd-boot |
| gurnard | Ubuntu 24.04 (Pantheon) | ✅ | ✅ (`tpm2-tools` installed explicitly) | _pending E2E_ | same `Containerfile.ubuntu` path as grouper |
| marlin | Arch | ✅ | ❌ **not built** | ❌ **not possible today** | `pacman`'s package list has no `tpm2-tools`/`tpm2-tss`, so `dracut-config.sh`'s `command -v tpm2_pcrread` probe finds nothing and omits the module. Installing `tpm2-tools` on Arch would fix this, but is unverified in this environment (no local build/registry access) — left for a follow-up with real build coverage. tunaOS#714 |
| guppy | Gentoo | ✅ | ❌ **not built** | ❌ **not possible today** | `Containerfile.gentoo` omits `tpm2-tss`/`pcsc` unconditionally — the emerge base installs neither `app-crypt/tpm2-tools` nor `pcscd` (see the Containerfile's own comment, tunaOS#714/prior LUKS run 31111959946). |

`tests/bats/test_luks_tpm2_support_matrix.bats` asserts the three ❌ rows
against the actual Containerfile omit lines / package lists, so this table
cannot silently drift out of sync with the code — if a variant's TPM2
posture changes (e.g. Arch gains a `tpm2-tools` install), that test breaks
until this table is updated too.

Filled in by the per-variant TPM-enrollment test: install → first installed
boot (passphrase, first-boot oneshot enrolls TPM2 in the background) → reboot
with no passphrase → confirm auto-unlock. `scripts/iso-e2e.sh --luks` with
`TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK=1` runs exactly this sequence and records
`TUNAOS_LUKS_E2E_TPM_AUTOUNLOCK_CONFIRMED` / `_FAILED` in the LUKS evidence
log. It's wired into `.github/workflows/luks-e2e.yml` via the
`tpm_autounlock` dispatch input (and a quarterly schedule) — narrowed to one
flavor per variant to bound cost, skipping the three variants above whose
initramfs cannot carry the module at all. See the LUKS-TPM tracking issue
(tunaOS#680).
