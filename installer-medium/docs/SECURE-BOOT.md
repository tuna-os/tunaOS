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
The date of each measurement is 2026-11-25.

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

The next commit adds this table.
