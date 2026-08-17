#!/usr/bin/env bats
# Every live-ISO desktop adapter must ARRANGE TO LAUNCH its installer.
#
# WHY THIS EXISTS. The live ISO has exactly one job: run the installer. Four of
# the five desktop adapters set that up; gnome and niri did not, and nothing
# noticed for as long as the repo has had five frontends.
#
#   gnome  no autostart at all — the app was pinned to the dash and left there
#   niri   a TODO: "add spawn-at-startup ... when the live config.kdl is
#          introduced"
#
# The cost was invisible because it looks identical to a working run from
# outside: the ISO builds, the VM boots, the desktop comes up. Run 31171184497
# captured 11 frames of the empty GNOME overview, reported 1 visual state and
# 0/10 transitions, and the job went green. installer-smoke.yml would have
# caught it — asserting the installer process is running is its entire purpose
# — but gnome was not in its flavor matrix until #1039.
#
# So this asserts the property directly, in a unit test that needs no VM: each
# adapter must contain SOME mechanism that starts the installer. It does not
# care which mechanism (XDG autostart, a systemd user unit, a compositor
# spawn), only that one is present, because prescribing the mechanism would
# have blocked niri — where a partial config.kdl would clobber niri's defaults.

SRC="${BATS_TEST_DIRNAME}/../../live-iso/common/src"
WORKFLOW="${BATS_TEST_DIRNAME}/../../.github/workflows/installer-smoke.yml"

# Flavor -> the app id its adapter must launch. Mirrors the case statement in
# customize-live.sh; if that mapping changes, this fails and points at both.
launcher_app() {
  case "$1" in
    gnome)  echo "org.bootcinstaller.Installer" ;;
    kde)    echo "org.tunaos.InstallerKde" ;;
    cosmic) echo "org.tunaos.InstallerCosmic" ;;
    niri)   echo "org.tunaos.InstallerNiri" ;;
    xfce)   echo "org.tunaos.InstallerXfce" ;;
  esac
}

@test "every desktop adapter arranges to launch its installer" {
  local missing=()
  for flavor in gnome kde cosmic niri xfce; do
    local f="${SRC}/desktop-${flavor}.sh"
    [ -f "$f" ] || { missing+=("${flavor}: no desktop-${flavor}.sh"); continue; }

    # Any of the three legitimate mechanisms counts.
    if grep -q "xdg/autostart" "$f" \
       || grep -q "systemd/user" "$f" \
       || grep -q "spawn-at-startup" "$f"; then
      continue
    fi
    missing+=("${flavor}: no autostart, user unit or spawn-at-startup")
  done

  if [ "${#missing[@]}" -ne 0 ]; then
    printf 'installer is never launched on:\n' >&2
    printf '  %s\n' "${missing[@]}" >&2
    false
  fi
}

@test "each adapter launches the app id customize-live.sh installs" {
  local wrong=()
  for flavor in gnome kde cosmic niri xfce; do
    local f="${SRC}/desktop-${flavor}.sh"
    [ -f "$f" ] || continue
    local app
    app="$(launcher_app "$flavor")"
    # A launcher that starts a DIFFERENT app id than the one baked into the
    # squash is the failure mode this catches: the session would come up and
    # try to run something that is not installed, which looks exactly like the
    # installer crashing on start.
    grep -q "$app" "$f" || wrong+=("${flavor}: does not reference ${app}")
  done

  if [ "${#wrong[@]}" -ne 0 ]; then
    printf 'launcher/app-id mismatch:\n' >&2
    printf '  %s\n' "${wrong[@]}" >&2
    false
  fi
}

@test "installer smoke selects a compositor per flavor" {
  [ -f "$WORKFLOW" ]
  grep -q 'kde)    COMPS="kwin_wayland"' "$WORKFLOW"
  grep -q 'cosmic) COMPS="cosmic-comp"' "$WORKFLOW"
  grep -q 'niri)   COMPS="niri"' "$WORKFLOW"
  grep -q 'xfce)   COMPS="xfwl4 labwc wayfire xfwm4"' "$WORKFLOW"
  grep -q 'gnome)  COMPS="gnome-shell"' "$WORKFLOW"
}

@test "installer smoke does not accept a different frontend as a fallback" {
  [ -f "$WORKFLOW" ]
  ! grep -q 'pgrep -af' "$WORKFLOW"
  grep -Fq 'grep -Fx' "$WORKFLOW"
}

@test "installer smoke gates GPU-dependent flavors on runner capability" {
  [ -f "$WORKFLOW" ]
  grep -Fq 'host-capabilities:' "$WORKFLOW"
  grep -Fq 'gpu_available' "$WORKFLOW"
  grep -Fq 'No DRM render node' "$WORKFLOW"
  grep -Fq 'select(.flavor == "gnome")' "$WORKFLOW"
}


@test "installer recipe backend does not need an executable source mount" {
  # Tacklebox bind-mounts live-customize read-only. Git may retain this helper
  # without the execute bit, so invoking it directly turns every flavor's ISO
  # build into exit 126 before the LUKS test even starts.
  grep -Fq '_backend_kv="$(bash "${SCRIPT_DIR}/installer-recipe-backend.sh")"' \
    "${SRC}/customize-live.sh"
}
