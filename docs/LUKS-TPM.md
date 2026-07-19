# Disk encryption & TPM2 auto-unlock

TunaOS installs (via fisherman) can encrypt the root filesystem with LUKS2.
You choose a **passphrase** during install. Optionally, after the system is up,
you can enroll this machine's **TPM2** chip so the disk unlocks automatically at
boot — no passphrase prompt.

## Why TPM enrollment is a post-install step (not the installer)

TPM2 auto-unlock works by *sealing* the unlock key to the machine's measured
boot state (PCRs **7** = Secure Boot state, **14** = MokList/shim). Those
measurements only exist once the **real installed system** boots — an installer
running from the live ISO measures *different* PCRs, so enrolling at install time
seals against the wrong state and the disk won't unlock. This is the same model
Universal Blue (`ublue-os-luks`), Bazzite, and Fedora Silverblue use, and why
`bootc install` doesn't do it either ([bootc#421](https://github.com/bootc-dev/bootc/issues/421)).

So: **the installer sets a passphrase; you opt into TPM auto-unlock afterward.**

## Enabling TPM2 auto-unlock

After installing and booting, run once:

```sh
ujust enable-luks-tpm2          # TPM only
ujust enable-luks-tpm2 --pin    # TPM + a PIN you set
```

(or `sudo tunaos-luks-tpm2-enroll`). It seals to PCRs 7+14, wires up
`/etc/crypttab`, and the next boot unlocks with no prompt. To revert:
`ujust disable-luks-tpm2`.

> **Keep your passphrase.** Updating firmware, toggling Secure Boot, or
> re-enrolling MOK keys changes PCR 7/14 — the TPM then refuses to unseal and you
> fall back to the passphrase. That's the security trade-off, by design.

## Variant support matrix

TPM2 auto-unlock needs the systemd TPM2 modules in the initramfs and a working
`/dev/tpmrm0`. Enrollment is exercised per variant by the LUKS-TPM E2E; results:

| Variant | Base | Encrypted install (passphrase) | TPM2 auto-unlock | Notes |
|---------|------|-------------------------------|------------------|-------|
| yellowfin | AlmaLinux Kitten 10 | ✅ (fisherman) | _pending E2E_ | |
| skipjack | CentOS Stream 10 | ✅ | _pending E2E_ | |
| albacore | AlmaLinux 10 | ✅ | _pending E2E_ | |
| bonito | Fedora 44 | ✅ | _pending E2E_ | |
| sailfin | openSUSE Tumbleweed | ✅ | _pending E2E_ | |
| flounder | Debian 13 Trixie | ✅ | _pending E2E_ | |
| grouper | Ubuntu 26.04 | ✅ | _pending E2E_ | composefs/systemd-boot |
| marlin | Arch | ✅ | _pending E2E_ | |
| guppy | Gentoo | ✅ | _pending E2E_ | |

Filled in by the per-variant TPM-enrollment test (install → passphrase boot →
`enable-luks-tpm2` → reboot → confirm auto-unlock). See the LUKS-TPM tracking issue.
