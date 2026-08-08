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

Filled in by the per-variant TPM-enrollment test: install → first installed
boot (passphrase, first-boot oneshot enrolls TPM2 in the background) → reboot
with no passphrase → confirm auto-unlock. `scripts/iso-e2e.sh --luks` with
`TUNAOS_E2E_VERIFY_TPM_AUTOUNLOCK=1` runs exactly this sequence and records
`TUNAOS_LUKS_E2E_TPM_AUTOUNLOCK_CONFIRMED` / `_FAILED` in the LUKS evidence
log — not yet wired into a scheduled workflow (see the header comment in
`.github/workflows/luks-e2e.yml`). See the LUKS-TPM tracking issue
(tunaOS#680).
