#!/usr/bin/env bats
# The initramfs names the variant's hostname, never the upstream one (tunaOS#4865).
#
# Falsification: make initrd-hostname.sh keep an existing DEFAULT_HOSTNAME
# (Fedora ships "fedora") and the replace case fails. Make the check accept an
# empty DEFAULT_HOSTNAME and the published-yellowfin case fails. Drop the
# printf from the identity module and the Debian-dracut case fails.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SEED="${REPO_ROOT}/build_scripts/initrd-hostname.sh"
CHECK="${REPO_ROOT}/build_scripts/checks/verify-initrd-hostname.sh"
MODULE="${REPO_ROOT}/build_scripts/dracut/99tunaos-identity/module-setup.sh"

setup() {
  ROOT="$(mktemp -d)"
  mkdir -p "${ROOT}/usr/lib" "${ROOT}/bin"
  export TUNAOS_SYSROOT="$ROOT"
  # lsinitrd -f <file> <image>: the fixture "image" is a directory tree.
  cat >"${ROOT}/bin/lsinitrd" <<'EOF'
#!/bin/sh
[ "$1" = -f ] && cat "$3/$2"
EOF
  chmod +x "${ROOT}/bin/lsinitrd"
  export PATH="${ROOT}/bin:${PATH}"
}

teardown() { rm -rf "$ROOT"; }

initramfs() { # <initrd-release text>: prints the path of a fixture image
  # A directory stands in for the image; the lsinitrd stub reads into it.
  mkdir -p "${ROOT}/img/usr/lib"
  printf '%s\n' "$1" >"${ROOT}/img/usr/lib/initrd-release"
  echo "${ROOT}/img"
}

@test "the seed replaces Fedora's DEFAULT_HOSTNAME=fedora" {
  printf 'NAME="Fedora Linux"\nDEFAULT_HOSTNAME="fedora"\n' >"${ROOT}/usr/lib/os-release"
  IMAGE_NAME=bonito run "$SEED"
  [ "$status" -eq 0 ]
  grep -qx 'DEFAULT_HOSTNAME="bonito"' "${ROOT}/usr/lib/os-release"
  [ "$(grep -c '^DEFAULT_HOSTNAME=' "${ROOT}/usr/lib/os-release")" -eq 1 ]
}

@test "the seed adds the key AlmaLinux does not ship" {
  printf 'NAME="AlmaLinux Kitten"\n' >"${ROOT}/usr/lib/os-release"
  IMAGE_NAME=yellowfin run "$SEED"
  [ "$status" -eq 0 ]
  grep -qx 'DEFAULT_HOSTNAME="yellowfin"' "${ROOT}/usr/lib/os-release"
}

@test "the seed folds a distro alias onto its variant" {
  IMAGE_NAME=opensuse run "$SEED" --print
  [ "$output" = sailfin ]
}

@test "the seed refuses to guess without a name" {
  run env -u IMAGE_NAME -u IMAGE_NAME_VARIANT "$SEED"
  [ "$status" -eq 1 ]
}

@test "the published yellowfin initrd-release fails the check" {
  printf 'DEFAULT_HOSTNAME="yellowfin"\n' >"${ROOT}/usr/lib/os-release"
  img="$(initramfs 'NAME="AlmaLinux Kitten"')"
  [ -d "$img" ]
  IMAGE_NAME=yellowfin run "$CHECK" "${img}"
  [ "$status" -eq 1 ]
  [[ "$output" == *"no DEFAULT_HOSTNAME"* ]]
}

@test "the seeded initrd-release passes the check" {
  printf 'DEFAULT_HOSTNAME="yellowfin"\n' >"${ROOT}/usr/lib/os-release"
  img="$(initramfs 'NAME="Yellowfin"
DEFAULT_HOSTNAME="yellowfin"
PRETTY_NAME="Yellowfin (Initramfs)"')"
  IMAGE_NAME=yellowfin run "$CHECK" "${img}"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_INITRD_HOSTNAME_OK hostname=yellowfin"* ]]
}

@test "a PRETTY_NAME carrying dracut's version fails (sailfin 'dracut-112+suse')" {
  # Falsification: accept any PRETTY_NAME that starts with the name and this passes.
  printf 'DEFAULT_HOSTNAME="sailfin"\n' >"${ROOT}/usr/lib/os-release"
  img="$(initramfs 'NAME="Sailfin"
DEFAULT_HOSTNAME="sailfin"
PRETTY_NAME="Sailfin dracut-112+suse.63.g62ea8ea-1 (Initramfs)"')"
  IMAGE_NAME=sailfin run "$CHECK" "${img}"
  [ "$status" -eq 1 ]
  [[ "$output" == *"want 'Sailfin (Initramfs)'"* ]]
}

identity_module() { # <initrd-release text>: runs the module's install(), prints the result
  mkdir -p "${ROOT}/initdir/usr/lib"
  printf '%s\n' "$1" >"${ROOT}/initdir/usr/lib/initrd-release"
  initdir="${ROOT}/initdir" dracutsysrootdir="${ROOT}" bash -c '. "$1"; install' _ "$MODULE"
  cat "${ROOT}/initdir/usr/lib/initrd-release"
}

@test "the identity module adds DEFAULT_HOSTNAME when Debian's dracut drops it (flounder)" {
  # Debian's dracut copied NAME and PRETTY_NAME but not DEFAULT_HOSTNAME, so the
  # check stopped every flounder build (canary flounder:xfce, run 44927176620).
  printf 'NAME="Flounder"\nDEFAULT_HOSTNAME="flounder"\n' >"${ROOT}/usr/lib/os-release"
  out="$(identity_module 'PRETTY_NAME="Debian GNU/Linux 13 (trixie) dracut-106 (Initramfs)"
NAME="Debian GNU/Linux"
ID=debian')"
  [[ "$out" == *'NAME="Flounder"'* ]]
  [[ "$out" == *'PRETTY_NAME="Flounder (Initramfs)"'* ]]
  [ "$(grep -c '^DEFAULT_HOSTNAME=' <<<"$out")" -eq 1 ]
  grep -qx 'DEFAULT_HOSTNAME="flounder"' <<<"$out"
  img="$(initramfs "$out")"
  IMAGE_NAME=flounder run "$CHECK" "${img}"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_INITRD_HOSTNAME_OK hostname=flounder"* ]]
}

@test "the identity module writes PRETTY_NAME when Debian's dracut left none (flounder)" {
  # run 45645343087 / flounder: initrd-release had NAME but no PRETTY_NAME line,
  # so the rewrite matched nothing and the check saw PRETTY_NAME=''.
  printf 'NAME="Flounder"\nDEFAULT_HOSTNAME="flounder"\n' >"${ROOT}/usr/lib/os-release"
  out="$(identity_module 'NAME="Debian GNU/Linux"
ID=debian')"
  [ "$(grep -c '^PRETTY_NAME=' <<<"$out")" -eq 1 ]
  grep -qx 'PRETTY_NAME="Flounder (Initramfs)"' <<<"$out"
}

@test "the identity module replaces an upstream DEFAULT_HOSTNAME dracut copied" {
  printf 'DEFAULT_HOSTNAME="bonito"\n' >"${ROOT}/usr/lib/os-release"
  out="$(identity_module 'NAME="Fedora Linux"
DEFAULT_HOSTNAME="fedora"
PRETTY_NAME="Fedora Linux 43 dracut-107 (Initramfs)"')"
  [ "$(grep -c '^DEFAULT_HOSTNAME=' <<<"$out")" -eq 1 ]
  grep -qx 'DEFAULT_HOSTNAME="bonito"' <<<"$out"
}
