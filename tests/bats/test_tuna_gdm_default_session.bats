#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/build_scripts/desktop/tuna-gdm-default-session.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${ROOT}"
  export TUNAOS_GDM_DEFAULT_ROOT="${ROOT}"
}

@test "fallback session pins Tuna on a fresh image" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx '[daemon]' "${ROOT}/etc/gdm/custom.conf"
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm/custom.conf"
  [ "$(grep -c '^FallbackSession=' "${ROOT}/etc/gdm/custom.conf")" -eq 1 ]
}

@test "fallback session fills in an existing daemon section" {
  mkdir -p "${ROOT}/etc/gdm"
  printf '[daemon]\nAutomaticLoginEnable=false\n' >"${ROOT}/etc/gdm/custom.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx '[daemon]' "${ROOT}/etc/gdm/custom.conf"
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm/custom.conf"
  grep -Fqx 'AutomaticLoginEnable=false' "${ROOT}/etc/gdm/custom.conf"
  [ "$(grep -c '^FallbackSession=' "${ROOT}/etc/gdm/custom.conf")" -eq 1 ]
}

@test "fallback session replaces a non-Tuna fallback" {
  mkdir -p "${ROOT}/etc/gdm"
  printf '[daemon]\nFallbackSession=gnome\n' >"${ROOT}/etc/gdm/custom.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm/custom.conf"
  run grep -Fxq 'FallbackSession=gnome' "${ROOT}/etc/gdm/custom.conf"
  [ "$status" -ne 0 ]
}

@test "the DefaultSession key GDM never reads is replaced, not kept" {
  # Published marlin:tuna (2026-10-28) shipped only DefaultSession=tuna.desktop,
  # and a fresh GDM 51.1 login started GNOME (tuna-os/tuna-desktop#813).
  mkdir -p "${ROOT}/etc/gdm"
  printf '# GDM configuration storage\n\n[daemon]\nDefaultSession=tuna.desktop\n\n[security]\n' \
    >"${ROOT}/etc/gdm/custom.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm/custom.conf"
  run grep -q '^DefaultSession=' "${ROOT}/etc/gdm/custom.conf"
  [ "$status" -ne 0 ]
  grep -Fqx '[security]' "${ROOT}/etc/gdm/custom.conf"
}

@test "running twice leaves one fallback session" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(grep -c '^FallbackSession=' "${ROOT}/etc/gdm/custom.conf")" -eq 1 ]
}

@test "fallback session uses the Debian config path" {
  mkdir -p "${ROOT}/etc/gdm3"
  printf '[daemon]\n' >"${ROOT}/etc/gdm3/daemon.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm3/custom.conf"
  [ ! -e "${ROOT}/etc/gdm/custom.conf" ]
}
