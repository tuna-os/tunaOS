#!/usr/bin/env bats
# Unit tests for build_scripts/bootc/dracut-config.sh
#
# The script exists to make "this image is composefs" and "its initramfs can
# mount erofs" the same fact rather than two that drift. Five of six variants
# enabled composefs and only Arch carried the driver, because the fix was made
# while chasing marlin and had nowhere shared to live.
#
# Run: bats tests/bats/test_bootc_dracut_config.bats

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
SCRIPT="${REPO_ROOT}/build_scripts/bootc/dracut-config.sh"

# Build a fake image tree: $1 = composefs yes/no, remaining args = driver names
# to present as modules.
_fixture() {
  local composefs="$1"; shift
  local root="${BATS_TEST_TMPDIR}/${composefs}-$*"
  root="${root// /_}"
  mkdir -p "${root}/usr/lib/ostree" "${root}/usr/lib/modules/6.1.0-test/kernel/fs"
  if [ "$composefs" = yes ]; then
    printf '[composefs]\nenabled = yes\n\n[sysroot]\nreadonly = true\n' \
      >"${root}/usr/lib/ostree/prepare-root.conf"
  else
    printf '[composefs]\nenabled = no\n\n[sysroot]\nreadonly = true\n' \
      >"${root}/usr/lib/ostree/prepare-root.conf"
  fi
  local drv
  for drv in "$@"; do
    mkdir -p "${root}/usr/lib/modules/6.1.0-test/kernel/fs/${drv}"
    touch "${root}/usr/lib/modules/6.1.0-test/kernel/fs/${drv}/${drv}.ko"
  done
  echo "$root"
}

_conf() { cat "${1}/usr/lib/dracut/dracut.conf.d/30-bootc-container-build.conf"; }

@test "composefs image gets the erofs driver" {
  local root; root="$(_fixture yes erofs overlay)"
  run env TUNAOS_SYSROOT="$root" bash "$SCRIPT"
  [ "$status" -eq 0 ]
  local conf; conf="$(_conf "$root")"
  [[ "$conf" == *"add_drivers"* ]]
  [[ "$conf" == *erofs* ]]
  [[ "$conf" == *overlay* ]]
}

@test "non-composefs image gets no composefs drivers" {
  # el10 is deliberately traditional ostree. Adding erofs there would be cargo
  # cult, and the point of detecting rather than hardcoding is that it doesn't.
  local root; root="$(_fixture no erofs overlay)"
  run env TUNAOS_SYSROOT="$root" bash "$SCRIPT"
  [ "$status" -eq 0 ]
  local conf; conf="$(_conf "$root")"
  [[ "$conf" != *erofs* ]]
}

@test "a driver the kernel lacks is skipped, not requested" {
  # dracut-install treats add_drivers on an unknown name as an error, so
  # listing erofs unconditionally would break any base that builds it in (=y)
  # or omits it — turning a fix for one variant into a build failure on others.
  local root; root="$(_fixture yes)"   # composefs, but NO modules present
  run env TUNAOS_SYSROOT="$root" bash "$SCRIPT"
  [ "$status" -eq 0 ]
  local conf; conf="$(_conf "$root")"
  [[ "$conf" != *"add_drivers"* ]]
  [[ "$output" == *"not a module"* ]]
}

@test "every image gets bootc, crypt and dm modules" {
  # crypt/dm named explicitly: openSUSE's dracut defaults to hostonly, so a
  # rebuild on a non-LUKS machine silently drops the modules that unlock the
  # disk, and the image boots to an emergency shell instead.
  local root; root="$(_fixture no)"
  run env TUNAOS_SYSROOT="$root" bash "$SCRIPT"
  [ "$status" -eq 0 ]
  local conf; conf="$(_conf "$root")"
  [[ "$conf" == *"add_dracutmodules"* ]]
  [[ "$conf" == *bootc* ]]
  [[ "$conf" == *crypt* ]]
  [[ "$conf" == *" dm "* ]]
}

@test "the 51bootc systemd path fix is written for every base" {
  # openSUSE's dracut leaves systemdsystemconfdir empty, so 51bootc's
  # wants-symlink lands at the initramfs root where systemd never scans:
  # the unit ships and is never pulled in, nothing consumes composefs=, and
  # switch-root finds no prepared root.
  local root; root="$(_fixture yes erofs)"
  run env TUNAOS_SYSROOT="$root" bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -qF 'systemdsystemconfdir=/etc/systemd/system' \
    "${root}/usr/lib/dracut/dracut.conf.d/30-fix-bootc-module.conf"
  grep -qF 'systemdsystemunitdir=/usr/lib/systemd/system' \
    "${root}/usr/lib/dracut/dracut.conf.d/30-fix-bootc-module.conf"
}

@test "passes shellcheck" {
  if command -v shellcheck &>/dev/null; then
    run shellcheck --severity=error --exclude=SC1091,SC2114 "$SCRIPT"
    [ "$status" -eq 0 ]
  else
    skip "shellcheck not installed"
  fi
}

@test "composefs is declared before dracut-config.sh reads it" {
  # dracut-config.sh derives its driver set from prepare-root.conf. A
  # Containerfile that runs it BEFORE writing that file gets composefs=0 and an
  # initramfs with no erofs — silently, because every step still exits 0.
  #
  # The fixture tests above cannot catch this: it is an ordering property of
  # the Containerfile, not of the script. Wiring arch had exactly this bug on
  # the first attempt.
  local cf
  for cf in "${REPO_ROOT}"/Containerfile.*; do
    grep -q 'dracut-config\.sh' "$cf" 2>/dev/null || continue
    local decl call
    decl=$(grep -n 'prepare-root\.conf' "$cf" | grep -v '^\s*#' | head -1 | cut -d: -f1)
    call=$(grep -n 'dracut-config\.sh' "$cf" | grep -vE ':[[:space:]]*#' | head -1 | cut -d: -f1)
    [ -n "$call" ] || continue
    if [ -n "$decl" ] && [ "$decl" -gt "$call" ]; then
      echo "FAIL: $(basename "$cf") writes prepare-root.conf at line ${decl}," >&2
      echo "      after dracut-config.sh at line ${call} — composefs will read as off." >&2
      return 1
    fi
  done
}
