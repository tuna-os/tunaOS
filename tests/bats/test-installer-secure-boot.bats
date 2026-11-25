#!/usr/bin/env bats
# Secure Boot stage and first-boot helper (tunaOS#4955).
#
# No root, no real key, no firmware: tuna-secure-boot reads EFI variables and
# sysfs from fixture trees (TUNA_SB_EFIVARS, TUNA_SB_SYSFS), and the stage
# script runs with --dry-run.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SB="${REPO_ROOT}/installer-medium/secure-boot"
GLOBAL=8be4df61-93ca-11d2-aa0d-00e098032b8c
DB=d719b2cb-3d3a-4596-a3bc-dad00e67656f
SHIM=605dab50-e046-4300-abb6-3dd810dd8b23

setup() {
  T="$(mktemp -d)"
  mkdir -p "${T}/efivars" "${T}/sys/kernel/security" "${T}/sys/class/tpm/tpm0/pcr-sha256"
  export TUNA_SB_EFIVARS="${T}/efivars" TUNA_SB_SYSFS="${T}/sys"
  export TUNA_SB_CERT="${SB}/certs/tunaos-sb.cer" TUNA_SB_SHARE="${T}/share"
  export TUNA_SB_MODE=tunaos-key
  echo "none [integrity] confidentiality" >"${T}/sys/kernel/security/lockdown"
  echo 2 >"${T}/sys/class/tpm/tpm0/tpm_version_major"
  echo 00A1 >"${T}/sys/class/tpm/tpm0/pcr-sha256/11"
}

teardown() {
  rm -rf "${T}"
}

# efivar NAME BYTE: a one-byte EFI variable (4 attribute bytes, then data).
efivar() {
  printf '\x07\x00\x00\x00' >"${T}/efivars/$1"
  printf "\\x$2" >>"${T}/efivars/$1"
}

# certvar NAME: an EFI variable whose data holds the tunaOS certificate.
certvar() {
  { printf '\x07\x00\x00\x00junk-before'; cat "${TUNA_SB_CERT}"; printf 'junk-after'; } >"${T}/efivars/$1"
}

@test "state: not a UEFI boot" {
  rmdir "${T}/efivars"
  run "${SB}/tuna-secure-boot" state
  [ "$status" -eq 0 ]
  [ "$output" = "no-uefi" ]
}

@test "state: Setup Mode wins over everything else" {
  efivar "SetupMode-${GLOBAL}" 01
  efivar "SecureBoot-${GLOBAL}" 00
  run "${SB}/tuna-secure-boot" state
  [ "$output" = "setup-mode" ]
}

@test "state: Secure Boot off" {
  efivar "SetupMode-${GLOBAL}" 00
  efivar "SecureBoot-${GLOBAL}" 00
  run "${SB}/tuna-secure-boot" state
  [ "$output" = "secure-boot-off" ]
}

@test "state: key enrolled by systemd-boot is found in db, not in MOK" {
  efivar "SecureBoot-${GLOBAL}" 01
  certvar "db-${DB}"
  run "${SB}/tuna-secure-boot" state
  [ "$output" = "enrolled-db" ]
}

@test "state: key enrolled by MokManager is found in MokListRT" {
  efivar "SecureBoot-${GLOBAL}" 01
  printf '\x07\x00\x00\x00other' >"${T}/efivars/db-${DB}"
  certvar "MokListRT-${SHIM}"
  run "${SB}/tuna-secure-boot" state
  [ "$output" = "enrolled-mok" ]
}

@test "state: Secure Boot on with another certificate is not-enrolled" {
  efivar "SecureBoot-${GLOBAL}" 01
  printf '\x07\x00\x00\x00other' >"${T}/efivars/db-${DB}"
  run "${SB}/tuna-secure-boot" state
  [ "$output" = "not-enrolled" ]
}

@test "state: distro-chain never looks for a tunaOS key" {
  efivar "SecureBoot-${GLOBAL}" 01
  TUNA_SB_CERT=/nonexistent TUNA_SB_MODE=distro-chain run "${SB}/tuna-secure-boot" state
  [ "$status" -eq 0 ]
  [ "$output" = "distro-on" ]
}

@test "an unknown or unset mode fails; there is no default" {
  TUNA_SB_MODE=grub run "${SB}/tuna-secure-boot" state
  [ "$status" -eq 2 ]
  [[ "$output" == *"unknown Secure Boot mode 'grub'"* ]]
  TUNA_SB_MODE="" run "${SB}/tuna-secure-boot" plan
  [ "$status" -ne 0 ]
}

@test "mode file is read when TUNA_SB_MODE is unset" {
  mkdir -p "${T}/share"
  echo distro-chain >"${T}/share/mode"
  efivar "SecureBoot-${GLOBAL}" 01
  TUNA_SB_MODE="" run "${SB}/tuna-secure-boot" state
  [ "$output" = "distro-on" ]
}

@test "plan: enrolled key seals now" {
  efivar "SecureBoot-${GLOBAL}" 01
  certvar "MokListRT-${SHIM}"
  run "${SB}/tuna-secure-boot" plan
  [ "$status" -eq 0 ]
  [[ "$output" == *"state=enrolled-mok"* ]]
  [[ "$output" == *"tpm_seal=now"* ]]
  [[ "$output" == *"string=sb.done.on"* ]]
}

@test "plan: Setup Mode on a tunaos-key cell enrols before the seal" {
  efivar "SetupMode-${GLOBAL}" 01
  run "${SB}/tuna-secure-boot" plan
  [[ "$output" == *"tpm_seal=after-enrol"* ]]
  [[ "$output" == *"action=oneshot-enrol"* ]]
  [[ "$output" == *"string=sb.handoff.setup-mode"* ]]
}

@test "plan: Setup Mode on a distro-chain cell has nothing to enrol" {
  efivar "SetupMode-${GLOBAL}" 01
  TUNA_SB_MODE=distro-chain run "${SB}/tuna-secure-boot" plan
  [[ "$output" == *"tpm_seal=now"* ]]
  [[ "$output" == *"action=none"* ]]
}

@test "plan: Secure Boot on without the key never seals to PCR 7" {
  efivar "SecureBoot-${GLOBAL}" 01
  run "${SB}/tuna-secure-boot" plan
  [[ "$output" == *"tpm_seal=none"* ]]
  [[ "$output" == *"string=sb.done.not-enrolled"* ]]
}

@test "check: all pass when the key is enrolled" {
  efivar "SecureBoot-${GLOBAL}" 01
  certvar "db-${DB}"
  run "${SB}/tuna-secure-boot" check
  [ "$status" -eq 0 ]
  [[ "$output" == *"[PASS] tunaOS key trusted: in the firmware db"* ]]
  [[ "$output" == *"6 passed, 0 failed"* ]]
}

@test "check: fails and says why when Secure Boot is off" {
  efivar "SecureBoot-${GLOBAL}" 00
  echo "[none] integrity confidentiality" >"${T}/sys/kernel/security/lockdown"
  rm "${T}/sys/class/tpm/tpm0/pcr-sha256/11"
  run "${SB}/tuna-secure-boot" check
  [ "$status" -eq 1 ]
  [[ "$output" == *"[FAIL] Secure Boot enabled"* ]]
  [[ "$output" == *"[FAIL] tunaOS key trusted"* ]]
  [[ "$output" == *"[FAIL] Kernel lockdown: mode is 'none'"* ]]
  [[ "$output" == *"[FAIL] Measured boot"* ]]
  [[ "$output" == *"2 passed, 4 failed"* ]]
}

@test "reseal dry-run prints the cryptenroll command for each volume" {
  TUNA_SB_LUKS_DEVICES="/dev/vda3 /dev/vdb1" run "${SB}/tuna-secure-boot" reseal --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"--tpm2-pcrs=7 --wipe-slot=tpm2 /dev/vda3"* ]]
  [[ "$output" == *"/dev/vdb1"* ]]
}

@test "stage-medium dry-run prints the tunaos-key layout" {
  run "${SB}/stage-medium.sh" tunaos-key /tmp/root /tmp/esp --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"<shim> -> EFI/BOOT/BOOTX64.EFI"* ]]
  [[ "$output" == *"<mokmanager> -> EFI/BOOT/mmx64.efi"* ]]
  [[ "$output" == *"<loader> -> EFI/BOOT/grubx64.efi"* ]]
  [[ "$output" == *"<cert> -> tunaos-secure-boot.cer"* ]]
  [[ "$output" == *"loader/keys/auto/PK.auth"* ]]
  [[ "$output" == *"secure-boot-enroll if-safe"* ]]
}

@test "stage-medium dry-run: distro-chain stages nothing" {
  run "${SB}/stage-medium.sh" distro-chain /tmp/root /tmp/esp --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"stages nothing"* ]]
  [[ "$output" != *"copy"* ]]
}

@test "stage-medium refuses an unknown mode" {
  run "${SB}/stage-medium.sh" grub /tmp/root /tmp/esp --dry-run
  [ "$status" -eq 1 ]
  [[ "$output" == *"unknown mode 'grub'"* ]]
}

@test "stage-medium distro-chain fails on a medium with no shim" {
  mkdir -p "${T}/esp" "${T}/root"
  run "${SB}/stage-medium.sh" distro-chain "${T}/root" "${T}/esp"
  [ "$status" -eq 1 ]
  [[ "$output" == *"REFUSED: shim missing: EFI/BOOT/BOOTX64.EFI"* ]]
}

@test "build-medium takes the Secure Boot mode from the cell row" {
  run "${REPO_ROOT}/installer-medium/build-medium.sh" albacore:gnome "${T}/m.iso" --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"stage-medium.sh distro-chain"* ]]
  [[ "$output" != *"sign-medium.sh"* ]]
  run "${REPO_ROOT}/installer-medium/build-medium.sh" tromso:kde "${T}/m.iso" --dry-run
  [ "$status" -eq 0 ]
  # A tunaos-key cell signs first, then stages.
  [[ "$output" == *"sign-medium.sh"*"stage-medium.sh tunaos-key"* ]]
  [[ "$output" == *"loader/keys/auto/db.auth"* ]]
}

@test "MEDIUM_SECURE_BOOT replaces the mode of the row, and an unknown mode stops the build" {
  MEDIUM_SECURE_BOOT=tunaos-key run "${REPO_ROOT}/installer-medium/build-medium.sh" albacore:gnome "${T}/m.iso" --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"stage-medium.sh tunaos-key"* ]]
  MEDIUM_SECURE_BOOT=bogus run "${REPO_ROOT}/installer-medium/build-medium.sh" tromso:kde "${T}/m.iso" --dry-run
  [ "$status" -ne 0 ]
}

@test "a given signed loader skips the sign step" {
  MEDIUM_SB_LOADER=/x/loader.signed run "${REPO_ROOT}/installer-medium/build-medium.sh" tromso:kde "${T}/m.iso" --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" != *"sign-medium.sh"* ]]
  [[ "$output" == *"stage-medium.sh tunaos-key"* ]]
}

@test "sign-medium without a key signs nothing and exits 3" {
  mkdir -p "${T}/esp/EFI/systemd"
  : >"${T}/esp/EFI/systemd/systemd-bootx64.efi"
  run env -u TUNAOS_SB_KEY -u TUNAOS_SB_KEY_URI -u TUNAOS_SB_CERT "${SB}/sign-medium.sh" "${T}/esp" "${T}/out"
  [ "$status" -eq 3 ]
  [[ "$output" == *"nothing signed"* ]]
  [ ! -e "${T}/out" ]
}

@test "ci-sign dry-run names the secrets and prints no key" {
  run "${SB}/ci-sign.sh" efi in.efi out.efi --dry-run
  [ "$status" -eq 0 ]
  [[ "$output" == *"--key <TUNAOS_SB_KEY> --cert <TUNAOS_SB_CERT>"* ]]
}
