#!/usr/bin/env bats
# The installer's variant mark must point at a resource that EXISTS.
#
# WHY THIS EXISTS. build_scripts/90-image-info.sh rewrites
# /etc/bootc-installer/recipe.json per variant, and it used to set
#
#   distro_logo = resource:///org/bootcinstaller/Installer/images/<variant>.png
#
# unconditionally. Every TunaOS mark in bootc-installer's GResource is an .svg
# — only bluefin, bluefin-lts and dakota are .png — so that path resolved for
# nobody. bootc-installer's apply_icon() catches the failure and logs a
# warning, so the welcome screen showed GTK's broken-image placeholder above a
# correctly branded "Welcome to Skipjack", and every gate stayed green: the
# process was running, the window was mapped, the title was right.
#
# Only looking at the picture found it (tuna-os/tunaOS#1056's live-ISO
# screenshot). This is the cheap regression check that does not need a picture.

SCRIPT="${BATS_TEST_DIRNAME}/../../build_scripts/90-image-info.sh"

# Upstream's set, from bootc_installer/bootc-installer.gresource.xml. If
# upstream adds a mark for grouper/marlin/redfin/sailfin, add it here AND to
# the case statement in 90-image-info.sh — this list existing separately is
# the price of not being able to read the GResource at image-build time.
KNOWN_MARKS="tunaos bonito skipjack albacore yellowfin"

@test "distro_logo uses .svg, never .png" {
  # .png would silently resolve to nothing for every TunaOS variant.
  run grep -n "Installer/images/.*\.png" "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "every variant maps to a mark that exists upstream" {
  # Mirrors the case statement. A variant that falls through must land on the
  # TunaOS mark, not on its own name.
  for variant in tunaos bonito skipjack albacore yellowfin grouper marlin redfin sailfin; do
    local mark
    case "$variant" in
      tunaos | bonito | skipjack | albacore | yellowfin) mark="$variant" ;;
      *) mark="tunaos" ;;
    esac
    # shellcheck disable=SC2076
    [[ " ${KNOWN_MARKS} " == *" ${mark} "* ]] || {
      echo "variant ${variant} maps to ${mark}, which upstream does not ship" >&2
      false
    }
  done
}

@test "the fallback branch is present so unmarked variants are not broken" {
  # grouper, marlin, redfin and sailfin have no mark of their own. Without the
  # fallback they get the same broken placeholder this file exists to prevent.
  run grep -c "images/tunaos.svg" "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "90-image-info.sh: rewrites recipe.json with valid syntax and correct imgref" {
  local tmp_dir="${BATS_TEST_TMPDIR}/recipe_test"
  mkdir -p "${tmp_dir}/etc/bootc-installer"
  local recipe_file="${tmp_dir}/etc/bootc-installer/recipe.json"
  cat >"${recipe_file}" <<'JSON'
{
  "distro_name": "TunaOS",
  "welcome_title": "Welcome to TunaOS",
  "tour": {
    "welcome": {"title": "Welcome to TunaOS", "description": "TunaOS workstation"}
  }
}
JSON

  # Test normal variant
  run bash -c "
    RECIPE_FILE='${recipe_file}'
    IMAGE_NAME='bonito'
    VARIANT_KEY='bonito'
    IMAGE_FLAVOR='gnome'
    IMAGE_PRETTY_NAME='Bonito'
    DISTRO_LOGO_RES='resource:///org/bootcinstaller/Installer/images/bonito.svg'
    BASE_OS_NAME='Fedora'
    DESKTOP_PRETTY_NAME='GNOME'
    IMAGE_REGISTRY='ghcr.io'
    IMAGE_VENDOR='tuna-os'
    $(sed -n '/TAG_SUFFIX=""/,/^PYEOF/p' "${SCRIPT}")
  "
  [ "$status" -eq 0 ]
  run jq -r '.imgref' "${recipe_file}"
  [ "$output" = "ghcr.io/tuna-os/bonito:gnome" ]
  run jq -r '.local_imgref' "${recipe_file}"
  [ "$output" = "containers-storage:ghcr.io/tuna-os/bonito:gnome" ]
  run jq -r '.tour.welcome.title' "${recipe_file}"
  [ "$output" = "Welcome to Bonito" ]

  # Test tag-suffixed variant (bonito-rawhide)
  run bash -c "
    RECIPE_FILE='${recipe_file}'
    IMAGE_NAME='bonito'
    VARIANT_KEY='bonito-rawhide'
    IMAGE_FLAVOR='gnome'
    IMAGE_PRETTY_NAME='Bonito'
    DISTRO_LOGO_RES='resource:///org/bootcinstaller/Installer/images/bonito.svg'
    BASE_OS_NAME='Fedora Rawhide'
    DESKTOP_PRETTY_NAME='GNOME'
    IMAGE_REGISTRY='ghcr.io'
    IMAGE_VENDOR='tuna-os'
    $(sed -n '/TAG_SUFFIX=""/,/^PYEOF/p' "${SCRIPT}")
  "
  [ "$status" -eq 0 ]
  run jq -r '.imgref' "${recipe_file}"
  [ "$output" = "ghcr.io/tuna-os/bonito:gnome-rawhide" ]
  run jq -r '.local_imgref' "${recipe_file}"
  [ "$output" = "containers-storage:ghcr.io/tuna-os/bonito:gnome-rawhide" ]

  # Test tag-suffixed variant (flounder-sid)
  run bash -c "
    RECIPE_FILE='${recipe_file}'
    IMAGE_NAME='flounder'
    VARIANT_KEY='flounder-sid'
    IMAGE_FLAVOR='kde'
    IMAGE_PRETTY_NAME='Flounder'
    DISTRO_LOGO_RES='resource:///org/bootcinstaller/Installer/images/tunaos.svg'
    BASE_OS_NAME='Debian Sid'
    DESKTOP_PRETTY_NAME='KDE Plasma'
    IMAGE_REGISTRY='ghcr.io'
    IMAGE_VENDOR='tuna-os'
    $(sed -n '/TAG_SUFFIX=""/,/^PYEOF/p' "${SCRIPT}")
  "
  [ "$status" -eq 0 ]
  run jq -r '.imgref' "${recipe_file}"
  [ "$output" = "ghcr.io/tuna-os/flounder:kde-sid" ]
  run jq -r '.local_imgref' "${recipe_file}"
  [ "$output" = "containers-storage:ghcr.io/tuna-os/flounder:kde-sid" ]
}
