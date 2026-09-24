#!/usr/bin/env bats
# The COSMIC dock pins only apps the image has (tunaOS#2192).
#
# The upstream default dock pinned cosmic-edit, cosmic-store and Firefox,
# which not every base installs, so a first boot showed broken icons.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/desktop/cosmic-dock.sh"

setup() {
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${ROOT}/usr/share/applications"
  FAV="${ROOT}/usr/share/cosmic/com.system76.CosmicAppList/v1/favorites"
}

app() { : >"${ROOT}/usr/share/applications/$1.desktop"; }

@test "pins exactly the installed COSMIC apps, in dock order" {
  app com.system76.CosmicSettings
  app com.system76.CosmicFiles
  app com.system76.CosmicTerm
  TUNAOS_COSMIC_DOCK_ROOT="$ROOT" bash "$SCRIPT"
  run cat "$FAV"
  [ "$output" = '[
    "com.system76.CosmicFiles",
    "com.system76.CosmicTerm",
    "com.system76.CosmicSettings",
]' ]
}

@test "never pins an app that is not installed" {
  app com.system76.CosmicFiles
  TUNAOS_COSMIC_DOCK_ROOT="$ROOT" bash "$SCRIPT"
  ! grep -q 'CosmicEdit\|CosmicStore\|firefox' "$FAV"
}

@test "writes nothing when no COSMIC app is installed" {
  TUNAOS_COSMIC_DOCK_ROOT="$ROOT" bash "$SCRIPT"
  [ ! -e "$FAV" ]
}

@test "every COSMIC manifest runs it" {
  local m
  for m in cosmic.yaml cosmic-arch.yaml; do
    grep -qx '  - cosmic-dock.sh' "${REPO_ROOT}/manifests/desktops/${m}" ||
      { echo "${m} does not run cosmic-dock.sh" >&2; return 1; }
  done
}
