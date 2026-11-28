#!/usr/bin/env bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CANONICAL="system_files/usr/share/backgrounds/tunaos/tunaos-default.jpg"
IMAGES="system_files/usr/share/wallpapers/TunaOS/contents/images"
PLASMA="${IMAGES}/1920x1080.jpg"

@test "Plasma wallpaper path resolves to the canonical desktop asset" {
  [ -f "${REPO_ROOT}/${CANONICAL}" ]
  [ -L "${REPO_ROOT}/${PLASMA}" ]

  local resolved
  resolved="$(realpath --relative-to="${REPO_ROOT}" "${REPO_ROOT}/${PLASMA}")"
  [ "$resolved" = "$CANONICAL" ]
}

# Plasma's image wallpaper picks a file of a package by its WIDTHxHEIGHT
# name. With only tunaos-default.jpg it logged "Unknown or unsupported
# background type ... inode/directory" and loaded no image. Fedora's Plasma
# then fell back to its default wallpaper; EL10 Plasma 6.7.5 left the whole
# desktop black, panel included (albacore:kde runs 46083819054 to
# 46146633530; 1920x1080.jpg drew it in run 46161253862).
@test "every image of the Plasma wallpaper package has a WIDTHxHEIGHT name" {
  local found=0 f
  for f in "${REPO_ROOT}/${IMAGES}"/*; do
    found=1
    [[ "$(basename "$f")" =~ ^[0-9]+x[0-9]+\.(jpg|jpeg|png|webp)$ ]] || {
      echo "not a WIDTHxHEIGHT name: $(basename "$f")"
      return 1
    }
  done
  [ "$found" -eq 1 ]
}
