#!/usr/bin/env bats
# The UEFI boot entry is named after the variant (tunaOS#4864).
#
# Falsification: the "upstream" cases lay down the files measured in the
# bonito and yellowfin images and require verify-efi-boot-label.sh to fail.
# Make efi-boot-label.sh skip either step and the matching "after" case fails.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
LABEL="${REPO_ROOT}/build_scripts/efi-boot-label.sh"
CHECK="${REPO_ROOT}/build_scripts/checks/verify-efi-boot-label.sh"

setup() {
  R="$(mktemp -d)"
  export TUNAOS_SYSROOT="$R"
  mkdir -p "${R}/usr/lib" "${R}/etc"
  printf 'NAME="Bonito"\nVERSION_ID=44\n' >"${R}/usr/lib/os-release"
  ln -s ../usr/lib/os-release "${R}/etc/os-release"
}

teardown() { rm -rf "$R"; }

utf16_csv() { # <path> <text>
  mkdir -p "$(dirname "$1")"
  { printf '\xff\xfe'; printf '%s\n' "$2" | iconv -f UTF-8 -t UTF-16LE; } >"$1"
}

fedora_files() {
  printf 'Fedora release 44 (Forty Four)\n' >"${R}/usr/lib/fedora-release"
  ln -s ../usr/lib/fedora-release "${R}/etc/fedora-release"
  ln -s fedora-release "${R}/etc/redhat-release"
  ln "${R}/etc/redhat-release" "${R}/etc/system-release"
  utf16_csv "${R}/usr/lib/efi/shim/16.1-7/EFI/fedora/BOOTAA64.CSV" \
    'shimaa64.efi,Fedora,,This is the boot entry for Fedora'
}

@test "the measured Fedora files fail the check" {
  command -v iconv >/dev/null || skip "iconv not installed"
  fedora_files
  run "$CHECK"
  [ "$status" -eq 1 ]
  [[ "$output" == *"bootupd would name the boot entry 'Fedora'"* ]]
  [[ "$output" == *"BOOTAA64.CSV: shimaa64.efi is labelled 'Fedora', want 'Bonito'"* ]]
}

@test "after efi-boot-label.sh both labels are the variant and the base files stay" {
  command -v iconv >/dev/null || skip "iconv not installed"
  fedora_files
  run "$LABEL"
  [ "$status" -eq 0 ]
  [ "$(readlink "${R}/etc/system-release")" = ../usr/lib/tunaos-release ]
  [ "$(cat "${R}/etc/system-release")" = "Bonito release 44" ]
  [ "$(cat "${R}/etc/redhat-release")" = "Fedora release 44 (Forty Four)" ]
  [ "$(head -c 2 "${R}/usr/lib/efi/shim/16.1-7/EFI/fedora/BOOTAA64.CSV" | od -An -tx1 | tr -d ' ')" = fffe ]
  run "$CHECK"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_EFI_LABEL_OK name=Bonito product=Bonito csvs=1"* ]]
}

@test "the legacy bootupd payload CSV is relabelled too" {
  command -v iconv >/dev/null || skip "iconv not installed"
  csv="${R}/usr/lib/bootupd/updates/EFI/almalinux/BOOTX64.CSV"
  utf16_csv "$csv" 'shimx64.efi,AlmaLinux Kitten,,This is the boot entry for AlmaLinux Kitten'
  run "$CHECK"
  [ "$status" -eq 1 ]
  "$LABEL"
  [ "$(iconv -f UTF-16 -t UTF-8 "$csv")" = 'shimx64.efi,Bonito,,This is the boot entry for Bonito' ]
}

@test "a base without system-release or shim passes on os-release NAME" {
  run "$CHECK"
  [ "$status" -eq 0 ]
  [[ "$output" == *"product=Bonito csvs=0"* ]]
}
