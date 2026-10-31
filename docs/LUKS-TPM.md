# Disk encryption & TPM2 auto-unlock

During installation, you choose a passphrase for the LUKS2 root filesystem. On the first boot, TunaOS enrolls the TPM2 auto-unlock key. After enrollment, the system boots without a passphrase prompt.

## Why TPM enrollment happens on first boot (not during the install)

TPM2 auto-unlock seals the key to the machine's measured boot state (PCR **7**, the Secure Boot state). The system measures PCR 7 after the installed system boots. The live installer measures a different PCR 7. If it enrolls the key, the installed system cannot unlock the disk. Universal Blue (`ublue-os-luks`), Bazzite, and Fedora Silverblue use this model. `bootc install` also follows it ([bootc#421](https://github.com/bootc-dev/bootc/issues/421)).

The installer sets a passphrase and schedules one-time enrollment for the next boot. On that boot, the installed system enrolls the TPM against its own PCR 7 and removes the staged key. You do not need to act. A `ConditionFirstBoot` oneshot does this ([fisherman#48](https://github.com/tuna-os/fisherman/pull/48)). An earlier version enrolled during installation. The key then failed to unseal on the installed system (tunaOS#679, tunaOS#680).

**First boot after install still shows the passphrase prompt once** — TPM2
isn't enrolled yet at that point, so the passphrase is still required. Every
boot after that should be prompt-free.

## Re-enrolling manually

You can also run enrollment by hand if you disabled it or need to re-seal after a firmware or Secure Boot change invalidates the old seal:

```sh
ujust enable-luks-tpm2          # TPM only
ujust enable-luks-tpm2 --pin    # TPM + a PIN you set
```

This command seals the key to PCRs **7+14** (Secure Boot state and MokList/shim). It uses more PCRs than automatic first-boot enrollment, which uses PCR 7. The command asks for your current passphrase. To revert either type, run `ujust disable-luks-tpm2`.

> **Keep your passphrase.** A firmware update, a Secure Boot change, or a new MOK key changes PCR 7/14. The TPM will then refuse to unseal the key. Use your passphrase to unlock the disk. This is the security trade-off.

## Variant support matrix

TPM2 auto-unlock needs the systemd `tpm2-tss` dracut module in the initramfs. The image build must also install TPM2 tools (such as `tpm2-tools`) because `dracut-install` omits modules with missing binaries. The machine must provide a working `/dev/tpmrm0` at boot. We can check two requirements from each base's package list and dracut config before boot. Only the runtime unlock needs an E2E boot test. The table marks each requirement:

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

`tests/bats/test_luks_tpm2_support_matrix.bats` checks the three ❌ rows against the Containerfile and package lists. The test fails if the code changes but the table does not. For example, if Arch adds `tpm2-tools`, update this table.

`tests/bats/test_luks_tpm2_enroll_script.bats` checks the enrollment script and its `ujust` commands. It also checks that manual enrollment uses PCR 7+14. The first-boot oneshot uses PCR 7 ([fisherman#48](https://github.com/tuna-os/fisherman/pull/48)).

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
