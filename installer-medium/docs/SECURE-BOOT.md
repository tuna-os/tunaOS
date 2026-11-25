# Secure Boot and key enrolment for the installer medium

Issue: [tunaOS#4955](https://github.com/tuna-os/tunaOS/issues/4955), part of
[#4905](https://github.com/tuna-os/tunaOS/issues/4905). Code:
`installer-medium/secure-boot/`.

The goal: no user learns a random password, and no user opens a firmware
menu.

## Owner decisions (2026-11-25)

- Use systemd-boot where the base has a signed systemd-boot. Use GRUB only
  where Secure Boot needs it.
- A base with a distro-signed chain gets mode `distro-chain`. The chain is
  shim, then the distro-signed loader, then the distro-signed kernel. The
  entries are Type #1. That mode has no tunaOS key and no enrolment.
- A base where tunaOS must sign gets mode `tunaos-key`. MokManager enrols the
  certificate from the ESP. systemd-boot enrols the key bundle in a VM, and
  offers it on firmware in Setup Mode.

## Verified facts

Each row names its source. "Not verified" marks a claim with no source.
The date of each measurement is 2026-11-25. These tables are evidence with a
date. They are not a live status.

### systemd

Source: `systemd/systemd` main at `94bb07689802` (263~devel). The medium pins
`5371d8fe424c`; rows marked (pin) were read at that commit too.

| Fact | Source |
|---|---|
| `secure-boot-enroll` takes `off`, `manual`, `if-safe`, `force`. The default is `if-safe`. | `src/boot/boot.c:1207-1218`, `:1651`; `man/loader.conf.xml:289-326` (v253) |
| systemd-boot looks for keys only in Setup Mode or Audit Mode. | `src/boot/boot.c:3329` |
| Each directory `/loader/keys/NAME/` becomes the menu entry `secure-boot-keys-NAME`. | `src/boot/boot.c:3352-3363` |
| Automatic enrolment applies only to the directory named `auto`. | `src/boot/boot.c:3366-3371`; (pin) `src/boot/boot.c:3319` |
| A bundle needs `db.auth`, `KEK.auth` and `PK.auth`. `dbx.auth` is optional. | `src/boot/secure-boot.c:138-143` |
| `if-safe` enrols only in a VM. The test is the CPUID hypervisor bit or SMBIOS. | `src/boot/secure-boot.c:87-91`; `src/boot/vmm.c:127-150` |
| `force` enrols on hardware too, after a 15 second warning that a key press stops. | `src/boot/secure-boot.c:94-121`; `man/loader.conf.xml:425-431` (v259) |
| A PK file with no signature needs the edk2 `CustomMode` variable. | `src/boot/secure-boot.c:151-175`, comment at `:41-53` |
| After enrolment systemd-boot reboots, because PCR 7 changes. | `src/boot/secure-boot.c:194-207` |
| `bootctl install --secure-boot-auto-enroll=yes` exists since v257. It needs a private key. | `NEWS:6044-6049`; `src/bootctl/bootctl.c:729-735` |
| That option writes one certificate into PK, KEK and db. It adds no Microsoft certificate. | `src/bootctl/bootctl-install.c:1203-1216`, `:1228` |
| `io.systemd.SysInstall.Run` has no Secure Boot input. | `src/shared/varlink-io.systemd.SysInstall.c:32-60`; (pin) same file, no match for `secure`, `enroll`, `certificate` |
| sysinstall calls `io.systemd.BootControl.Install` with four inputs. None is a key or certificate. | `src/sysinstall/sysinstall.c:1216-1225`; `src/shared/varlink-io.systemd.BootControl.c:131-147` |
| The OS can ask for one boot into the key entry: `bootctl set-oneshot secure-boot-keys-auto`. | `src/boot/boot.c:1700-1713`, `:1954-1958`, `:3315-3320` |
| That one-shot works only in Setup Mode or Audit Mode, because the entry exists only then. | `src/boot/boot.c:3329` |

Not verified: a one-shot boot into the key entry on real firmware. The rows
above come from the source, not from a boot.

edk2 (`SecurityPkg/Library/AuthVariableLib/AuthService.c:719-721`, master):
when the firmware is in Setup Mode, it accepts KEK and db with no signature
check. It checks the
PK signature only when `PcdRequireSelfSignedPk` is set. Other firmware can be
stricter, so CI signs each `.auth` file.

### shim and MokManager

Source: `rhboot/shim` main at `e794a714339b`.

| Fact | Source |
|---|---|
| shim starts MokManager when the loader fails the signature check. | `shim.c:442-451` |
| MokManager is `mm<arch>.efi` in the directory of shim. | `shim.h:151` |
| shim also starts MokManager when the OS set `MokNew` or `MokAuth`. | `mok.c:236-245` |
| MokManager first shows a 10 second countdown: "Press any key to perform MOK management". | `MokManager.c:2157-2180`, `:2236` |
| `MokTimeout` changes that countdown. Only an OS can set it, so the first boot always has 10 seconds. | `MokManager.c:2164-2171` |
| "Enroll key from disk" is always in the menu. | `MokManager.c:2375-2377` |
| The user picks a volume, then a file. The file name must end in `.cer`, `.der` or `.crt`. | `lib/simple_file.c:388-426`; `MokManager.c:2025-2030`, `:2076-2084` |
| The file must be one DER certificate. | `MokManager.c:1945-1967` |
| That path asks "Enroll the key(s)?" and takes no password. | `MokManager.c:1970` (`auth` is `FALSE`), `:971-990` |
| A set MOK password (`MokPWStore`) is asked first, on each visit. | `MokManager.c:2233`, `:2116-2150` |
| A request that the OS stages in `MokNew` always needs the password in `MokAuth`. | `MokManager.c:2402` (`auth` is `TRUE`), `:926-949` |
| shim measures the certificate that verified the loader into PCR 7. It measures `MokList` into PCR 14. | `README.tpm`; `tpm.c:393-426`; `mok.c:1158-1176` |
| The default loader name of shim is `grub<arch>.efi`. | `Make.defaults:31` |

So the MokManager flow is five steps, not one screen:

1. Press a key.
2. Choose "Enroll key from disk".
3. Pick the volume.
4. Pick the file.
5. Answer "Yes". Then choose "Reboot".
 No step needs a password. The OS cannot stage the
request without a password.

### Dakota today

Source: `projectbluefin/dakota` main at `1d9a814`.

| Fact | Source |
|---|---|
| The chain is the Fedora shim (16.1-7, Microsoft-signed), then systemd-boot under the name `grubx64.efi`, then the kernel. | `files/secure-boot/dakota-secure-boot:15-18`, `:88-101`; `elements/bluefin/fedora-shim.bst:21-23` |
| Dakota signs systemd-boot, the fwupd loader and the kernel modules with one key. | `elements/bluefin/signed-efi.bst:33-46`; `files/boot-keys/sign.sh:63-69` |
| CI writes the key from the secret `DAKOTA_SECURE_BOOT_KEY`. | `files/boot-keys/sign.sh:14-17` |
| The public certificate ships as `/usr/lib/dakota/secure-boot/dakota-secure-boot.der`. | `elements/bluefin/signed-efi.bst:43-46` |
| An installed system enrols through `MokNew` with the fixed password `dakota`. | `files/secure-boot/dakota-secure-boot:36`, `:618-626` |
| Dakota adds a TPM2 slot bound to no PCR for the switch, then seals again on the first boot with Secure Boot on. | `files/secure-boot/dakota-secure-boot:160-168`, `:215-262` |
| Dakota ships no `/loader/keys` bundle. | no match for `loader/keys` in the tree |
| The spike enrolled from the ESP with MokManager: one reboot and no password. PCR 4, 7 and 14 were the same in the live boot and the installed boot. | ahmedadan's [gist](https://gist.github.com/ahmedadan/48b7687dffde49336f78149f8d054b70), "Results" |

### Signed systemd-boot per base

The data lives in `installer-medium/secure-boot/bases.toml`. A test keeps
this table in step with that file. The table is evidence with a date, not a
live status: measure again before a cell changes its mode.

Method: download the package, then run `sbverify --list` on the loader. Then
run `sbverify --cert` with the certificate from the `.vendor_cert` section of
that base's own shim. "yes" means the signature chain verifies. No row comes
from a boot.

| Base | systemd-boot package | Signer | Shim accepts it | Result | Evidence |
|---|---|---|---|---|---|
| AlmaLinux 10 | systemd-boot-unsigned-257-33.el10.alma.2 (AppStream) | none | no | grub, `distro-chain` | sbverify --list systemd-bootx64.efi: No signature table present |
| AlmaLinux Kitten 10 | systemd-boot-unsigned-257-35.el10.alma.1 (AppStream) | none | no | grub, `distro-chain` | sbverify --list systemd-bootx64.efi: No signature table present |
| CentOS Stream 10 | systemd-boot-unsigned-257-35.el10 (AppStream) | none | no | grub, `distro-chain` | sbverify --list systemd-bootx64.efi: No signature table present |
| RHEL 10 | not verified: the RHEL repositories are not public | not verified | unknown | grub, `distro-chain` | none for RHEL; CentOS Stream 10 ships only systemd-boot-unsigned |
| Fedora 44 | systemd-boot-unsigned-259.10-1.fc44 (updates) | none | no | grub, `distro-chain` | sbverify --list systemd-bootx64.efi: No signature table present |
| Fedora Rawhide | systemd-boot-x64-262-1.fc46 (also in Fedora 45) | fedora-signer-20250530 / fedora-ca-20250530 | no | grub, `distro-chain` | sbverify --cert fedoraca systemd-bootx64.efi.signed: Signature verification failed; grubx64.efi carries a second, 2020-CA signature and verifies |
| Fedora ELN | systemd-boot-unsigned-262.2-1.eln159 (AppStream) | none | no | grub, `distro-chain` | sbverify --list systemd-bootx64.efi: No signature table present |
| Hummingbird | systemd-boot-unsigned-261.2-1.1.hum1 (public-hummingbird); not in the image | none | no | grub, `distro-chain` | sbverify --list systemd-bootx64.efi: No signature table present; image quay.io/hummingbird-community/bootc-os:latest of 2026-11-25 |
| Ubuntu 26.04 | systemd-boot-efi 259.9-0ubuntu0.1 (universe); no systemd-boot-efi-signed in any component | none | no | grub, `distro-chain` | sbverify --list systemd-bootx64.efi: No signature table present |
| Ubuntu 24.04 | systemd-boot-efi 255.4-1ubuntu8.19 (universe) | none | no | grub, `distro-chain` | sbverify --list systemd-bootx64.efi: No signature table present |
| Ubuntu interim | systemd-boot-efi 257.9-0ubuntu2.5 (25.10), 261.3-0ubuntu3 (26.10), 262.1-1ubuntu1 (27.04 devel), all universe | none | no | grub, `distro-chain` | sbverify --list systemd-bootx64.efi: No signature table present, each of the three |
| Debian 13 | systemd-boot-efi-amd64-signed 257.13-1~deb13u1 (main) | Debian Secure Boot Signer 2024 - systemd-boot / Debian Secure Boot CA | yes | systemd-boot, `distro-chain` | sbverify --cert <shim vendor cert> systemd-bootx64.efi.signed: Signature verification OK |
| Debian sid | systemd-boot-efi-amd64-signed 262.2-1 (main) | Debian Secure Boot Signer 2024 - systemd-boot / Debian Secure Boot CA | yes | systemd-boot, `distro-chain` | sbverify --cert <shim vendor cert> systemd-bootx64.efi.signed: Signature verification OK |
| openSUSE Tumbleweed | systemd-boot-262.2-1.1 (oss) | openSUSE Secure Boot Signkey / openSUSE Secure Boot CA | yes | systemd-boot, `distro-chain` | sbverify --cert <shim vendor cert> systemd-bootx64.efi: Signature verification OK |
| Arch Linux | systemd-262.2-1 (core) | none | no | systemd-boot, `tunaos-key` | sbverify --list systemd-bootx64.efi: No signature table present; shimx64.efi: no Microsoft signature |
| Gentoo | sys-apps/systemd-262.1, sys-apps/systemd-utils-262 (source builds) | whoever builds: secureboot.eclass signs with the key of the builder | no | systemd-boot, `tunaos-key` | the ebuilds call secureboot_auto_sign; the binhost packages hold no EFI file |
| tromso (BuildStream) | kde-linux-system/replace-signed-systemd-boot.bst, systemd v260 (tuna-os/tromso 8a0986d) | none: the element only copies files | no | systemd-boot, `tunaos-key` | recipe read only; the published image was not pulled |
| xfce-linux (BuildStream) | gnome-build-meta 50.4 junction, systemd 261.2 (tuna-os/xfce-linux 6c04e23) | GNOME VENDOR key: the public snakeoil test key of gnome-build-meta, so it counts as unsigned | no | systemd-boot, `tunaos-key` | image ghcr.io/tuna-os/xfce-linux nightly-20261102: sbverify --cert SECURE_BOOT_VENDOR_CRT systemd-bootx64.efi: OK |

What the rows mean:

- **Debian 13, Debian sid and openSUSE Tumbleweed** have a signed systemd-boot
  that their shim accepts. They can use systemd-boot with `distro-chain`.
- **Fedora Rawhide and Fedora 45** sign systemd-boot with the 2025 Fedora CA.
  The current shim (16.1-7) holds only the 2020 CA, so it refuses that file.
  GRUB has two signatures and still verifies. Rawhide stays on GRUB until a
  shim with the 2025 CA ships.
- **EL10, Fedora 44, ELN, Hummingbird and each Ubuntu release** ship only an
  unsigned systemd-boot. They stay on GRUB with `distro-chain`.
- **Arch, Gentoo, tromso and xfce-linux** have no distro signature that a
  Microsoft-signed shim accepts. tunaOS must sign: `tunaos-key`.
- No base has a systemd-boot with a Microsoft signature.

Not verified:

- RHEL 10. Its repositories are not public. The row copies the result for CentOS Stream 10.
- The kernel signer for Debian sid, openSUSE, and the Ubuntu interim releases.
- The published tromso image. The row comes from the recipe at `8a0986d`.
- A boot on real firmware for any row, and the SBAT and dbx state there.
- aarch64, except Debian 13 (signed, accepted) and Fedora Rawhide (signed,
  refused by the x64 shim certificate).
- Points 2 and 3 of #4955: bootc support for `--bootloader systemd` per
  backend, and distro-signed UKIs. This work did not measure them.

## The two modes

A cell names its mode. No script has a default mode, and an unknown mode
stops the build.

### `distro-chain`

`secureboot.py check` verifies the medium and stages nothing.

- The trust root is the shim on the ESP. A Microsoft UEFI CA must sign it.
- The loader and each kernel must verify against a certificate inside that
  shim. The check runs `sbverify --cert`; it never compares names.
- `--pin-sha256` also pins the distro certificate from `bases.toml`.
- A UKI that the distro did not sign stops the build. That includes a UKI
  with a tunaOS signature, because this mode has no tunaOS key.
- A `loader/keys` directory or a `.cer` file on the ESP stops the build.
- `secureboot.py entry` writes a Type #1 entry, and only for a kernel that
  passes the check.

### `tunaos-key`

`secureboot.py stage` verifies each input, then copies the files below.

| ESP path | File |
|---|---|
| `EFI/BOOT/BOOTX64.EFI`, `EFI/tunaos/shimx64.efi` | the Fedora shim, as Dakota uses it |
| `EFI/BOOT/mmx64.efi`, `EFI/tunaos/mmx64.efi` | MokManager, next to shim |
| `EFI/BOOT/grubx64.efi`, `EFI/tunaos/grubx64.efi` | systemd-boot with the tunaOS signature |
| `tunaos-secure-boot.cer`, `EFI/tunaos/tunaos-secure-boot.cer` | the public certificate, DER |
| `loader/keys/auto/{PK,KEK,db}.auth` | the key bundle for systemd-boot |
| `loader/loader.conf` | `secure-boot-enroll if-safe` |

The stage stops when one of these is true:

- shim has no signature from a Microsoft UEFI CA;
- MokManager fails the shim certificate;
- systemd-boot, a UKI, an add-on or a kernel on the ESP has no tunaOS
  signature;
- an `.auth` file has no signature;
- an `.auth` payload differs from the bundle that `build-esl` makes.

The last rule keeps the Microsoft certificates in the bundle.

Decisions in this mode:

- **The directory is `auto`, not `tunaos`.** systemd-boot enrols by itself
  only from `/loader/keys/auto/`. Another name gives a manual menu entry only.
- **The bundle comes from public certificates.** PK holds the tunaOS
  certificate. KEK and db hold it and each Microsoft certificate in
  `certs/manifest.toml`. Those are two KEK CAs and five db CAs, with the
  Option ROM CA of 2023.
- **CI signs the `.auth` files.** Firmware in Setup Mode can demand a PK that
  has a signature. A file with no signature works only on OVMF.
- **`if-safe` is the default.** A VM in Setup Mode enrols with no prompt. Real
  firmware in Setup Mode gets the menu entry "Enroll Secure Boot keys: auto".
- **`force` is an opt-in.** Set `MEDIUM_SB_ENROLL=force`; the tool then needs
  `--allow-force`. systemd-boot then enrols on real firmware after 15
  seconds. Use it only for a fleet with known hardware.
- **tunaOS becomes the platform key owner** on a machine that enrols the
  bundle. See the threat notes.

### What the image must ship

A `tunaos-key` image (tromso, xfce-linux) ships these files. This is a
contract for those repositories; this PR does not change them.

- `/usr/lib/tunaos/secure-boot/shimx64.efi` and `mmx64.efi`, from the Fedora
  shim package, with the checksum in a pin.
- `/usr/lib/tunaos/secure-boot/tunaos-secure-boot.cer`.
- `/usr/lib/tunaos/secure-boot/keys/auto/{PK,KEK,db}.auth`.
- `/usr/lib/tunaos/secure-boot/mode` with the text `tunaos-key`.
- `/usr/lib/systemd/boot/efi/systemd-bootx64.efi.signed`.
- `/usr/bin/tuna-secure-boot`.
- A kernel or UKI with the tunaOS signature.

### How a BuildStream image gets these files

tuna-os/tromso and tuna-os/brussels build with BuildStream. BuildStream keeps
each source in its cache, and the CI of those repositories publishes that
cache. So the key must not be a source of the build.

The publish job of each repository adds the files as one layer. The job runs
`installer-medium/secure-boot/image/sign-image.sh` after the build and before
the push. The cosign signature and the promotion then name the digest that
has the layer.

`sign-image.sh` does these steps:

1. It takes systemd-boot and each `vmlinuz` out of the image. The image does
   not run.
2. It removes each signature that the build made. gnome-build-meta signs
   systemd-boot with a public test key, and that signature must not ship.
3. It signs systemd-boot as `systemd-bootx64.efi.signed` and each `vmlinuz`
   in place. `ci-sign.sh` is the only script that reads the key.
4. It builds the key bundle and signs the three `.auth` files.
5. It adds the Fedora shim and MokManager from `image/shim.toml`. The pin has
   the URL, the sha256, the licence and the source package. The two files
   keep the signatures of Fedora and Microsoft.
6. It adds the certificate, `mode`, `provenance.toml` and `tuna-secure-boot`.

`image/verify-image.sh` checks the result and needs no key. It also stages
the files into a scratch ESP with `secureboot.py stage`. So an image that
passes gives a medium that the stage step accepts.

These images have no UKI. The boot entry is Type #1: a kernel, an initramfs
and a command line. Only systemd-boot and the kernel have the tunaOS
signature. See the threat notes.

## The CI step that signs

Only CI signs. `ci-sign.sh` is the interface:

```bash
python3 installer-medium/secure-boot/secureboot.py build-esl --out esl/
installer-medium/secure-boot/ci-sign.sh auth esl/ keys/auto/
installer-medium/secure-boot/ci-sign.sh efi systemd-bootx64.efi systemd-bootx64.efi.signed
```

| Input | Source |
|---|---|
| `TUNAOS_SB_KEY` | organisation secret: the PEM private key |
| `TUNAOS_SB_CERT` | organisation secret: the PEM certificate |
| `TUNAOS_SB_KEY_URI` | optional `pkcs11:` URI for an HSM or KMS key; replaces `TUNAOS_SB_KEY` |

Rules that the script enforces:

- `TUNAOS_SB_CERT` must equal `certs/tunaos-sb.crt`, or the step stops.
- The key must match the certificate, or the step stops.
- The key file exists only on tmpfs, with mode 0600, while the script runs.
- The script refuses `set -x`, and it prints no key.

The committed certificate: `CN=TunaOS Secure Boot Signing 2026`, RSA 2048,
valid to 2036-11-22. Its SHA-256 fingerprint is
`D2:6E:13:44:87:FC:8F:99:43:0E:41:6B:3F:BD:8F:AE:EF:4B:CD:FC:A1:09:B1:39:7E:29:A7:B3:1B:3C:48:2C`.
A test pins it and fails one year before the expiry date.

## What the user sees

### `distro-chain` cell

Nothing. The medium boots with Secure Boot on, as the distro media do. The
install adds no key and shows no extra screen.

### `tunaos-key` cell, Secure Boot on (most new PCs)

1. shim refuses systemd-boot and starts MokManager.
2. The user does the five MokManager steps. No step needs a password.
3. The PC restarts and boots the medium. It does not ask again.
4. The install seals the disk to PCR 7 and shows the recovery key.

The enrolment happens before the installer runs, because the medium cannot
boot without it. `strings.md` holds the text for the download page.

### `tunaos-key` cell in a VM with no keys

systemd-boot enrols the bundle and restarts the VM once. No prompt shows.

### `tunaos-key` cell, real firmware in Setup Mode

The medium boots with Secure Boot off. The installer runs
`tuna-secure-boot plan`, which prints `tpm_seal=after-enrol`. The handoff
page offers two choices:

- **Add the keys and restart.** The daemon runs
  `bootctl set-oneshot secure-boot-keys-auto` and restarts. systemd-boot
  shows a countdown of 15 seconds, enrols and restarts. The install then
  continues with Secure Boot on.
- **Install without Secure Boot.** The install continues.

### `tunaos-key` cell, Secure Boot off

The medium boots. The done page says that Secure Boot is off.

## Threat notes

### PCR 7 and the TPM2 slot

The installer seals the LUKS TPM2 slot to PCR 7. PCR 7 holds the Secure Boot
state, PK, KEK, db, dbx, and each certificate that verified a boot file.
shim adds the certificate that verified the loader. So a key change moves
PCR 7, and the TPM then refuses to unlock.

The rule: **seal only when PCR 7 is final for the installed chain.**

| State from `tuna-secure-boot plan` | `tpm_seal` | Why |
|---|---|---|
| `enrolled-db`, `enrolled-mok`, `distro-on` | `now` | The live boot and the installed boot use the same shim, loader signer and keys. The spike measured equal PCR 7 values. |
| `secure-boot-off` | `now` | PCR 7 stays the same until the user turns Secure Boot on. |
| `setup-mode` (`tunaos-key`) | `after-enrol` | A seal made now breaks at enrolment. Enrol first, then install. |
| `not-enrolled`, `no-uefi` | `none` | Use the recovery key or a passphrase only. |

The TPM slot needs a new seal in these cases:

- The user turns Secure Boot on, or off, after the install.
- The user enrols the key bundle after the install.
- A firmware update or `fwupd` changes db or dbx.
- A new shim comes with a different vendor certificate, or the tunaOS key
  rotates.
- The user enrols or removes a MOK. That also moves PCR 14.

How the installer avoids a lockout:

- Enrolment comes before the seal in each flow above.
- The install always shows a recovery key (tuna-os/fisherman#521).
- `tuna-secure-boot reseal` seals again to the current PCR 7. It asks for
  the recovery key when the TPM no longer unlocks the disk.

### Other notes

- **A Type #1 image has files with no signature.** On tromso and
  brussels, shim checks systemd-boot. systemd-boot then asks shim to check
  the kernel.
  No part of the chain checks the initramfs, the boot entry or the kernel
  command line. The command line holds the composefs digest of the root. A
  person who can write to the ESP can change the initramfs. That person can
  also point the boot at a different root. Secure Boot does not stop that. PCR 7 does
  not change in that case, so the TPM2 slot still unlocks. A signed UKI
  closes this gap. Those images do not build one yet.
- **Kernel modules.** The Secure Boot layer does not sign modules. Brussels
  modules carry the public test signature of gnome-build-meta. Tromsø
  modules have none. The kernel does not enforce module signatures until
  lockdown is on, and no image turns lockdown on.
- **Who can reach the key in CI.** The key belongs in the GitHub environment
  `secure-boot-signing` of tunaOS, tromso and brussels. GitHub gives an
  environment secret only to a job that names the environment. The branch
  policy admits `main` and `stable` only. A job that signs names the
  environment on those branches, and one step of it gets the key. In this
  repository `tests/test_secure_boot_environment.py` fails if any other job
  reads `TUNAOS_SB_KEY` or `TUNAOS_SB_CERT`.

  State on 2026-11-25: the environment exists, but it holds no secret.
  `TUNAOS_SB_KEY` is still an organisation secret for the three repositories.
  A fork gets no secret. A person with write access can add a workflow on a
  branch, and that workflow can read the key. This stops when the owner runs
  `tunaos-secure-boot-lockdown.sh` with the key file. The script sets the
  environment secrets and deletes the organisation secrets.

  After that, two gaps stay. No ruleset protects the name `stable`, so a
  person with write access can create that branch and sign from it. This
  repository does not use `stable`; remove it from the policy of this
  repository. Also, the environment has no required reviewers, so a change
  that merges to `main` can use the key.
- **One key signs everything.** The tunaOS key signs the loader and the
  kernel. On enrolled firmware it is also PK and KEK. A leak of that key
  breaks each machine that trusts it. The key has no offline root.
- **PK owner.** On a machine that enrols the bundle, the holder of the tunaOS
  key can change KEK and db. The Microsoft KEK stays, so dbx updates work.
- **A MOK is wider than db.** A MOK lets shim load any file with that
  signature. The kernel also trusts MOK keys for modules on some bases.
- **MokManager has no proof of origin.** The user trusts the file on the
  medium. An attacker with a changed medium can offer a different file. The
  MokManager screen shows the certificate before "Yes".
- **`force` can stop the boot of a PC** when its option ROMs need a
  certificate outside the bundle. The Microsoft certificates lower that
  risk; they do not remove it.
- **Expired certificates.** The Microsoft 2011 certificates expired in 2026.
  Firmware does not check the date, and old option ROMs still need them.

## Not solved

- **A password-free enrolment from the OS.** A request in `MokNew` always
  needs a password. So the OS cannot stage the key for a user.
- **No systemd-boot enrolment in User Mode.** The key entry
  exists only in Setup Mode. That user needs the MokManager steps.
- **The 10 second window.** A user who presses no key gets a failed boot.
- **The restart after a one-shot enrolment.** The firmware must boot the
  medium again. A different systemd-boot on the PC can use the one-shot
  first. No test covers that.
- **A leaf certificate as PK and KEK.** The tunaOS certificate has
  `CA:FALSE`. `sbverify` and `sbvarsign` accept that profile in the tests. No
  real firmware has enrolled it yet.
- **No image installs the helper.** Nothing puts `tuna-secure-boot` or the
  `mode` file into the live layer or an image yet. No workflow calls
  `ci-sign.sh`. `reseal` has only a dry-run test.
- **The FAT label of the ESP.** MokManager shows it. The medium build does
  not set `TUNAOS-ESP` yet.
- **The live add-on** (`build-live-addon.sh`) has no signature step yet. The
  stage refuses it until CI signs it with `ci-sign.sh efi`.
- **The image side.** `image/sign-image.sh` signs a sibling image in its
  publish job. A test signed and checked a published image with a throwaway
  key. No publish run with the real key has passed yet. No boot with Secure
  Boot on has used such an image.
- **No UKI for tromso and brussels.** See the first threat note.
- **The installed ESP.** `bootctl install` and bootc copy only the signed
  systemd-boot. `fishermand` must copy shim, MokManager and the certificate
  (tuna-os/fisherman#521). No unit refreshes them after an update.
- **dbx updates and PCR 7.** A signed PCR policy or `systemd-pcrlock` solves
  that. This work does not add one.
- **Key rotation and revocation** for the tunaOS key, and an SBAT entry for
  the files that tunaOS signs.
- **Fedora Rawhide on systemd-boot**, until a shim with the 2025 CA ships.
- **A boot test.** Stage 4 of the e2e track (#4910) must prove each mode
  with Secure Boot on. No test here boots firmware.

## Config fields for the resolver

This PR does not edit `tunaos.toml`. Each `[[installer_medium.cells]]` row
needs these fields:

| Field | Values | Use |
|---|---|---|
| `secure_boot` | `"distro-chain"` or `"tunaos-key"`, required | `stage-medium.sh` mode; replaces `MEDIUM_SECURE_BOOT` |
| `secure_boot_enroll` | `"if-safe"` (default), `"manual"`, `"off"`, `"force"`; only with `tunaos-key` | `loader.conf` |
| `secure_boot_vendor_sha256` | list of sha256, optional; only with `distro-chain` | `check --pin-sha256` |
| `secure_boot_reason` | text, required | why the cell has this mode; cite `bases.toml` |

Rules for the validator:

- `secure_boot = "tunaos-key"` needs `bootloader = "systemd-boot"`.
- `bootloader = "systemd-boot"` with `distro-chain` needs a base whose
  `bases.toml` row says `shim_accepts = "yes"`.
- `secure_boot_enroll` is an error on a `distro-chain` cell.

## Traps found in this work

| Symptom | Cause | Fix |
|---|---|---|
| `openssl x509 -fingerprint -sha256 -ext ...` prints a digest that no other tool gives. | OpenSSL 4.1 hashes a copy with only the named extensions. The digest `A0:AE:D3:13...` for the tunaOS certificate came from that. | Take the digest with no `-ext`, or run `sha256sum` on the DER file. The test pins `d26e1344...`. |
| A real shim has "no `.vendor_cert` section". | A PE header holds 8 name bytes. Longer names are `/N` offsets into the COFF string table. | `pe_sections` reads the string table. A test builds such a file. |
| `tuna-secure-boot plan` printed a state for an unknown mode. | bash does not pass `set -e` into `$(...)`. | `shopt -s inherit_errexit`; a bats test covers the unknown mode. |
| systemd-boot offers the keys but never enrols by itself. | The directory has a name other than `auto`. | Stage under `/loader/keys/auto/`. |
