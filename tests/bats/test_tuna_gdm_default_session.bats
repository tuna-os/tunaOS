#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/build_scripts/desktop/tuna-gdm-default-session.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${ROOT}"
  export TUNAOS_GDM_DEFAULT_ROOT="${ROOT}"
}

@test "default session pins Tuna on a fresh image" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx '[daemon]' "${ROOT}/etc/gdm/custom.conf"
  grep -Fqx 'DefaultSession=tuna.desktop' "${ROOT}/etc/gdm/custom.conf"
  [ "$(grep -c '^DefaultSession=' "${ROOT}/etc/gdm/custom.conf")" -eq 1 ]
}

@test "default session fills in an existing daemon section" {
  mkdir -p "${ROOT}/etc/gdm"
  printf '[daemon]\nAutomaticLoginEnable=false\n' >"${ROOT}/etc/gdm/custom.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx '[daemon]' "${ROOT}/etc/gdm/custom.conf"
  grep -Fqx 'DefaultSession=tuna.desktop' "${ROOT}/etc/gdm/custom.conf"
  grep -Fqx 'AutomaticLoginEnable=false' "${ROOT}/etc/gdm/custom.conf"
  [ "$(grep -c '^DefaultSession=' "${ROOT}/etc/gdm/custom.conf")" -eq 1 ]
}

@test "default session replaces a non-Tuna default" {
  mkdir -p "${ROOT}/etc/gdm"
  printf '[daemon]\nDefaultSession=gnome.desktop\n' >"${ROOT}/etc/gdm/custom.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'DefaultSession=tuna.desktop' "${ROOT}/etc/gdm/custom.conf"
  run grep -Fxq 'DefaultSession=gnome.desktop' "${ROOT}/etc/gdm/custom.conf"
  [ "$status" -ne 0 ]
}

@test "default session uses the Debian config path" {
  mkdir -p "${ROOT}/etc/gdm3"
  printf '[daemon]\n' >"${ROOT}/etc/gdm3/daemon.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'DefaultSession=tuna.desktop' "${ROOT}/etc/gdm3/custom.conf"
  [ ! -e "${ROOT}/etc/gdm/custom.conf" ]
}
