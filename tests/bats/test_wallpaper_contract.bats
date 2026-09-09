#!/usr/bin/env bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CANONICAL="system_files/usr/share/backgrounds/tunaos/tunaos-default.png"
PLASMA="system_files/usr/share/wallpapers/TunaOS/contents/images/tunaos-default.png"

@test "Plasma wallpaper path resolves to the canonical desktop asset" {
  [ -f "${REPO_ROOT}/${CANONICAL}" ]
  [ -L "${REPO_ROOT}/${PLASMA}" ]

  local resolved
  resolved="$(realpath --relative-to="${REPO_ROOT}" "${REPO_ROOT}/${PLASMA}")"
  [ "$resolved" = "$CANONICAL" ]
}
