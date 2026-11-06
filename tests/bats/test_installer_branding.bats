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
REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

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

@test "unmarked variants use the shipped generic TunaOS logo" {
  grep -q 'DISTRO_LOGO_RES="/usr/share/pixmaps/tunaos.svg"' "$SCRIPT"
  [ -f "${BATS_TEST_DIRNAME}/../../system_files/usr/share/pixmaps/tunaos.svg" ]
}

# NOTE: the build-time recipe rewrite (90-image-info.sh recipe.json branding,
# imgref/local_imgref interpolation, URI/data preservation) is executed
# end to end by the pytest Image harness (tests/test_anime_finalization.py
# consumers: test_identity_publish_integration.py, test_installer_recipe_refs.py),
# which runs the actual script against redirected roots — not a sed-extracted
# fragment of it. This file covers ref resolution, ISO payload binding, and
# the wiring between them.

@test "published tracking ref stays canonical while each ISO supplies its exact payload ref" {
  run env IMAGE_REGISTRY=registry.example:5000 REPO_ORGANIZATION=acme/team \
    bash -c 'cd "$1"; ./scripts/published-image-ref.sh bonito-rawhide gnome-nvidia ghcr' \
    _ "${REPO_ROOT}"
  [ "$status" -eq 0 ]
  [ "$output" = "registry.example:5000/acme/team/bonito:gnome-nvidia-rawhide" ]
  run env IMAGE_REGISTRY=registry.example:5000 REPO_ORGANIZATION=acme/team \
    bash -c 'cd "$1"; source scripts/lib/image.sh; tunaos_image_ref bonito-rawhide gnome-nvidia ghcr gnome-nvidia-rawhide-linux-amd64' \
    _ "${REPO_ROOT}"
  [ "$status" -eq 0 ]
  [ "$output" = "registry.example:5000/acme/team/bonito:gnome-nvidia-rawhide-linux-amd64" ]
  run env IMAGE_REGISTRY=registry.example:5000 REPO_ORGANIZATION=acme/team \
    bash -c 'cd "$1"; source scripts/lib/image.sh; tunaos_image_ref bonito-rawhide gnome-nvidia ghcr gnome-nvidia' \
    _ "${REPO_ROOT}"
  [ "$status" -eq 0 ]
  [ "$output" = "registry.example:5000/acme/team/bonito:gnome-nvidia-rawhide" ]

  # Explicit local tag chain (just iso bonito-rawhide gnome local gnome-testing 1):
  # Tracking ref stays bonito:gnome-rawhide while tacklebox embeds bonito:gnome-rawhide-testing from localhost
  run env IMAGE_REGISTRY=registry.example:5000 REPO_ORGANIZATION=acme/team \
    bash -c 'cd "$1"; ./scripts/published-image-ref.sh bonito-rawhide gnome ghcr' \
    _ "${REPO_ROOT}"
  [ "$status" -eq 0 ]
  [ "$output" = "registry.example:5000/acme/team/bonito:gnome-rawhide" ]
  run bash -c 'cd "$1"; source scripts/lib/image.sh; tunaos_image_ref bonito-rawhide gnome local gnome-testing' \
    _ "${REPO_ROOT}"
  [ "$status" -eq 0 ]
  [ "$output" = "localhost/bonito-rawhide:gnome-testing" ]
  run env IMAGE_REGISTRY=registry.example:5000 REPO_ORGANIZATION=acme/team \
    bash -c 'cd "$1"; source scripts/lib/image.sh; tunaos_image_ref bonito-rawhide gnome ghcr gnome-testing' \
    _ "${REPO_ROOT}"
  [ "$status" -eq 0 ]
  [ "$output" = "registry.example:5000/acme/team/bonito:gnome-rawhide-testing" ]

  grep -q 'PAYLOAD_REF=$(tunaos_image_ref "$VARIANT" "$FLAVOR" ghcr "$TAG")' \
    "${REPO_ROOT}/scripts/build-iso-tacklebox.sh"
  grep -q 'export TUNA_LIVE_PAYLOAD_REF=%q.*PAYLOAD_REF' \
    "${REPO_ROOT}/scripts/build-iso-tacklebox.sh"
  grep -q 'export TUNA_LIVE_PAYLOAD_REF=%q.*ref' \
    "${REPO_ROOT}/scripts/build-iso-group.sh"
  grep -q 'live_customize: \[$customize\]' "${REPO_ROOT}/scripts/build-iso-group.sh"
  grep -q 'recipe_payload.py" "$RECIPE_FILE"' "${REPO_ROOT}/live-iso/common/src/customize-live.sh"
  grep -q 'TUNA_LIVE_PAYLOAD_REF' "${REPO_ROOT}/live-iso/common/src/recipe_payload.py"

  local tmp_dir="${BATS_TEST_TMPDIR}/payload-ref"
  mkdir -p "${tmp_dir}"
  local recipe_file="${tmp_dir}/recipe.json"
  local payload_module="${REPO_ROOT}/live-iso/common/src/recipe_payload.py"

  for item in \
    "registry.example:5000/acme/team/bonito:gnome-nvidia-rawhide|registry.example:5000/acme/team/bonito:gnome-nvidia-rawhide-linux-amd64" \
    "registry.example:5000/acme/team/bonito:gnome-nvidia-rawhide|registry.example:5000/acme/team/bonito:gnome-nvidia-rawhide" \
    "registry.example:5000/acme/team/bonito:gnome-rawhide|registry.example:5000/acme/team/bonito:gnome-rawhide-testing"; do
    tracking_ref="${item%%|*}"
    payload="${item#*|}"
    printf '{"imgref":"%s"}\n' "$tracking_ref" >"$recipe_file"
    run env TUNA_LIVE_PAYLOAD_REF="$payload" python3 "${payload_module}" \
      "$recipe_file" systemd true xfs
    [ "$status" -eq 0 ]
    run jq -r '.imgref, .local_imgref' "$recipe_file"
    expected="${tracking_ref}"$'\n'"containers-storage:$payload"
    [ "$output" = "$expected" ]
    run jq -e --arg payload "containers-storage:$payload" '.local_imgref == $payload' "$recipe_file"
    [ "$status" -eq 0 ]
  done
  printf '{"imgref":"registry.example:5000/acme/team/bonito:gnome-nvidia-rawhide"}\n' >"$recipe_file"
  run env -u TUNA_LIVE_PAYLOAD_REF python3 "${payload_module}" \
    "$recipe_file" systemd true xfs
  [ "$status" -ne 0 ]
  run jq -e 'has("local_imgref") | not' "$recipe_file"
  [ "$status" -eq 0 ]
  printf '{"imgref":"registry.example:5000/acme/team/bonito:gnome-nvidia-rawhide","local_imgref":"containers-storage:stale-tracking-ref"}\n' >"$recipe_file"
  grep -q "echo 'export TUNA_LIVE_DEFER_LOCAL_IMGREF=1'" \
    "${REPO_ROOT}/.github/workflows/live-overlay.yml"
  run env TUNA_LIVE_DEFER_LOCAL_IMGREF=1 python3 "${payload_module}" \
    "$recipe_file" systemd true xfs
  [ "$status" -eq 0 ]
  run jq -e 'has("local_imgref") | not' "$recipe_file"
  [ "$status" -eq 0 ]
}
