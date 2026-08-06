#!/usr/bin/env bats
# Containerfile.ubuntu is the ONLY caller of the per-DE build_scripts/desktop
# scripts. Every other base — el10, debian, arch, opensuse, gentoo — installs
# its desktop through the manifest-driven install-desktop.sh. That asymmetry is
# the bug generator this file guards.
#
# Two things follow from it, and both have bitten:
#
#   1. A per-DE script invoked from Containerfile.ubuntu runs with PKG_MGR=apt
#      and nothing else. If it has no apt branch it falls through to the dnf
#      code — and there is no dnf in that image. desktop/cosmic.sh had exactly
#      that shape, so grouper:cosmic could not build at all. The gap was known
#      well enough to be worked around (weekly-desktop-screenshots.yml excluded
#      the cell) but the flavour stayed declared with build_image: true.
#
#   2. Whatever a per-DE script installs has to be repeated in the manifest for
#      the other bases. gnome.sh says so in its own comment — "Ubuntu builds
#      take this script path, not the manifest, so both must list it" — which
#      is the duplication VISION.md calls out as something to retire.
#
# The fix for a failure here is normally to move the stage onto
# install-desktop.sh, not to add another apt branch.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# Every `desktop/<name>.sh <arg>` invocation in a Containerfile, as
# "<containerfile> <script> <arg>".
desktop_script_calls() {
  grep -hoE 'build_scripts/desktop/[a-z0-9-]+\.sh [a-z-]+' "${REPO_ROOT}"/Containerfile.* |
    sed 's|build_scripts/desktop/||' || true
}

@test "no Containerfile invokes a per-DE script that has no branch for its package manager" {
  # Only Containerfile.ubuntu still calls the per-DE scripts, and it is apt.
  local line script fail=0
  while read -r script _arg; do
    [ -n "$script" ] || continue
    case "$script" in
    install-desktop.sh | configure-desktop-runtime.sh | gnome-extensions.sh | zfs.sh) continue ;;
    esac
    [ -f "${REPO_ROOT}/build_scripts/desktop/${script}" ] || {
      echo "FAIL: Containerfile.ubuntu calls desktop/${script}, which does not exist" >&2
      fail=1
      continue
    }
    if ! grep -qE 'PKG_MGR"?\]?\]? *== *"apt"' "${REPO_ROOT}/build_scripts/desktop/${script}"; then
      echo "FAIL: Containerfile.ubuntu calls desktop/${script} but it has no apt branch." >&2
      echo "      PKG_MGR is apt there, so the script falls through to its dnf" >&2
      echo "      code and dies on a command this image does not have." >&2
      echo "      Prefer moving the stage to install-desktop.sh over adding" >&2
      echo "      another apt branch — see the header of this file." >&2
      fail=1
    fi
  done < <(grep -oE 'build_scripts/desktop/[a-z0-9-]+\.sh [a-z-]+' "${REPO_ROOT}/Containerfile.ubuntu" |
    sed 's|build_scripts/desktop/||' | sort -u)
  [ "$fail" -eq 0 ]
}

@test "the per-DE scripts are called from Containerfile.ubuntu and nowhere else" {
  # If this fails, a second base has grown a per-DE call and the duplication
  # this file documents just doubled. Route the new one through the manifest.
  local f fail=0
  for f in "${REPO_ROOT}"/Containerfile.*; do
    case "$(basename "$f")" in Containerfile.ubuntu) continue ;; esac
    if grep -qE 'build_scripts/desktop/(gnome|kde|niri|xfce|cosmic)\.sh' "$f"; then
      echo "FAIL: $(basename "$f") calls a per-DE desktop script." >&2
      echo "      Every base except Containerfile.ubuntu installs its desktop" >&2
      echo "      via install-desktop.sh + manifests/desktops/*.yaml." >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}

@test "COSMIC on apt is manifest-driven, and names packages that exist there" {
  local manifest="${REPO_ROOT}/manifests/desktops/cosmic.yaml"

  # Containerfile.ubuntu must not have regrown a cosmic.sh call.
  run grep -q 'desktop/cosmic\.sh' "${REPO_ROOT}/Containerfile.ubuntu"
  [ "$status" -ne 0 ]
  run grep -q 'install-desktop\.sh cosmic' "${REPO_ROOT}/Containerfile.ubuntu"
  [ "$status" -eq 0 ]

  # The apt section must carry the PPA — COSMIC is not in the Ubuntu archive.
  run grep -q 'ppa:hepp3n/cosmic-epoch' "$manifest"
  [ "$status" -eq 0 ]

  # cosmic-icon-theme is the Fedora/EL10 name and is published by neither the
  # PPA nor the Ubuntu archive; apt's name is cosmic-icons. A single
  # unresolvable name fails the whole transaction, so this is not cosmetic.
  local apt_block
  apt_block="$(awk '/^  apt:/{f=1;next} /^  [a-z]+:/{f=0} f' "$manifest")"
  run grep -q 'cosmic-icons' <<<"$apt_block"
  [ "$status" -eq 0 ]
  run grep -q 'cosmic-icon-theme' <<<"$apt_block"
  [ "$status" -ne 0 ]
}
