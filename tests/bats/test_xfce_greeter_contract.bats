#!/usr/bin/env bats
# The one desktop hole no other gate could see: xfce.sh installs its greeter
# via install_available, and greetd's stock config (`agreety --cmd /bin/sh`)
# boots to a text prompt while display-manager.service reads ACTIVE — so a
# missing gtkgreet shipped a green image whose login screen is a shell.
# xfce_greetd_greeter_contract() in verify-desktop-experience.sh closes it.
# These tests extract the real function and drive it through every branch.

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
SCRIPT="${REPO_ROOT}/build_scripts/checks/verify-desktop-experience.sh"

# Run the extracted function with a controllable PATH (which commands exist)
# and a fixture root (what /etc/greetd/config.toml says, $2, what
# /etc/greetd/environments lists, $3, and the greetd-gtkgreet.sh wrapper
# /usr/libexec/tunaos/greetd-session, $4). require_command is redefined with
# the script's real semantics: missing command → exit 1.
run_contract() {
  local root="${BATS_TEST_TMPDIR}/${BATS_TEST_NUMBER}"
  local bin="${root}/bin"
  rm -rf "$root"
  mkdir -p "$bin" "${root}/etc/greetd"
  local cmd
  for cmd in $1; do
    printf '#!/bin/sh\nexit 0\n' >"${bin}/${cmd}"
    chmod +x "${bin}/${cmd}"
  done
  if [ -n "${2:-}" ]; then
    printf '%s\n' "$2" >"${root}/etc/greetd/config.toml"
  fi
  if [ -n "${3:-}" ]; then
    printf '%s\n' "$3" >"${root}/etc/greetd/environments"
  fi
  if [ -n "${4:-}" ]; then
    mkdir -p "${root}/usr/libexec/tunaos"
    printf '%s\n' "$4" >"${root}/usr/libexec/tunaos/greetd-session"
  fi

  local fn
  fn="$(awk '/^xfce_greetd_greeter_contract\(\)/,/^}/' "$SCRIPT")"
  PATH="${bin}:/usr/bin:/bin" TUNAOS_VERIFY_ROOT="$root" bash -c "
    command() { builtin command \"\$@\"; }
    require_command() { builtin command -v \"\$1\" >/dev/null || { echo \"missing required command: \$1\" >&2; exit 1; }; }
    ${fn}
    xfce_greetd_greeter_contract && echo CONTRACT_PASS
  "
}

@test "the contract function was actually extracted" {
  run awk '/^xfce_greetd_greeter_contract\(\)/,/^}/' "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"gtkgreet"* ]]
  [[ "$output" == *"}"* ]]
}

@test "lightdm images are exempt — greetd is not their DM" {
  # xfce.sh enables lightdm whenever it exists; the greetd config is
  # irrelevant on that branch even if greetd is also installed.
  run run_contract "lightdm greetd"
  [ "$status" -eq 0 ]
  [[ "$output" == *CONTRACT_PASS* ]]
}

@test "no DM at all is not this contract's failure (require_any_unit owns it)" {
  run run_contract ""
  [ "$status" -eq 0 ]
  [[ "$output" == *CONTRACT_PASS* ]]
}

@test "greetd without gtkgreet fails naming the missing greeter" {
  run run_contract "greetd cage" 'command = "cage -s -- gtkgreet -l"'
  [ "$status" -eq 1 ]
  [[ "$output" == *"missing required command: gtkgreet"* ]]
}

@test "greetd with gtkgreet but no cage fails — gtkgreet cannot own a VT" {
  run run_contract "greetd gtkgreet" 'command = "cage -s -- gtkgreet -l"'
  [ "$status" -eq 1 ]
  [[ "$output" == *"missing required command: cage"* ]]
}

@test "greetd whose config still runs stock agreety fails even with gtkgreet installed" {
  # Installed-but-not-wired is exactly how the silent text prompt ships:
  # xfce.sh only rewrites config.toml when both binaries landed, so a
  # regression there leaves agreety configured.
  run run_contract "greetd gtkgreet cage" 'command = "agreety --cmd /bin/sh"'
  [ "$status" -eq 1 ]
  [[ "$output" == *"agreety"* || "$output" == *"does not launch gtkgreet"* ]]
}

@test "greetd with gtkgreet, cage, a gtkgreet config and a session list passes" {
  run run_contract "greetd gtkgreet cage" 'command = "cage -s -- gtkgreet -s /etc/greetd/gtkgreet.css"' 'startxfce4 --wayland'
  [ "$status" -eq 0 ]
  [[ "$output" == *CONTRACT_PASS* ]]
}

@test "greetd launching gtkgreet through the greetd-gtkgreet.sh wrapper passes" {
  # config.toml names /usr/libexec/tunaos/greetd-session, which execs
  # gtkgreet under cage; the contract follows the wrapper.
  run run_contract "greetd gtkgreet cage" 'command = "/usr/libexec/tunaos/greetd-session"' 'startxfce4 --wayland' \
    $'#!/usr/bin/env bash\nexec cage -s -- gtkgreet -s /etc/greetd/gtkgreet.css'
  [ "$status" -eq 0 ]
  [[ "$output" == *CONTRACT_PASS* ]]
}

@test "a greetd wrapper that does not exec gtkgreet fails" {
  run run_contract "greetd gtkgreet cage" 'command = "/usr/libexec/tunaos/greetd-session"' 'startxfce4 --wayland' \
    $'#!/usr/bin/env bash\nexec agreety --cmd /bin/sh'
  [ "$status" -eq 1 ]
  [[ "$output" == *"does not launch gtkgreet"* ]]
}

@test "greetd with gtkgreet but no session list fails — a login would start nothing" {
  # gtkgreet starts the selected entry of `-c` plus /etc/greetd/environments;
  # gtkgreet 0.8 ships no environments file (tunaOS#4491).
  run run_contract "greetd gtkgreet cage" 'command = "cage -s -- gtkgreet -s /etc/greetd/gtkgreet.css"'
  [ "$status" -eq 1 ]
  [[ "$output" == *"session list"* ]]
}

@test "a missing config.toml under greetd fails (stock config path)" {
  run run_contract "greetd gtkgreet cage"
  [ "$status" -eq 1 ]
  [[ "$output" == *"does not launch gtkgreet"* ]]
}

@test "the xfce case actually calls the contract" {
  # The function existing is worthless if the case never runs it.
  run bash -c "awk '/^xfce\)/,/^	;;/' '$SCRIPT' | grep -v '^\s*#' | grep -c 'xfce_greetd_greeter_contract'"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "the xfce manifest configures greetd with greetd-gtkgreet.sh after xfce-greeter.sh" {
  # xfce-greeter.sh installs gtkgreet, cage and the session entry and writes
  # no greetd config; greetd-gtkgreet.sh writes it, including the session
  # list, and is a no-op unless gtkgreet and cage are already installed.
  run bash -c "awk '/^\[desktops\.xfce\]/{f=1;next} /^\[/{f=0} f' '${REPO_ROOT}/tunaos.toml' | grep -oE '\"(xfce-greeter|greetd-gtkgreet)\"' | tr -d '\"' | paste -sd ' '"
  [ "$status" -eq 0 ]
  [ "$output" = "xfce-greeter greetd-gtkgreet" ]
  ! grep -q '/etc/greetd/config.toml' "${REPO_ROOT}/build_scripts/desktop/xfce-greeter.sh"
}

# Falsification: remove the [initial_session] exemption from
# xfce_greetd_greeter_contract and the live-medium test below exits 1 with
# "does not launch gtkgreet" (yellowfin-xfce, iso-builder run 43429679278).
@test "the live ISO's greetd autologin config is not a missing greeter" {
  run run_contract "greetd gtkgreet cage" $'[default_session]\nuser = "liveuser"\ncommand = "systemd-cat -t tunaos-live-session dbus-run-session startxfce4 --wayland xfwl4"\n\n[initial_session]\nuser = "liveuser"\ncommand = "systemd-cat -t tunaos-live-session dbus-run-session startxfce4 --wayland xfwl4"'
  [ "$status" -eq 0 ]
  [[ "$output" == *CONTRACT_PASS* ]]
}

@test "an [initial_session] that does not start XFCE is still judged as stock agreety" {
  run run_contract "greetd gtkgreet cage" $'[initial_session]\nuser = "liveuser"\ncommand = "agreety --cmd /bin/sh"'
  [ "$status" -eq 1 ]
  [[ "$output" == *"does not launch gtkgreet"* ]]
}

# Run the session-entry block of xfce-greeter.sh against a fixture root. The
# block is cut out of the real script and its absolute path is pointed at the
# fixture, so what runs is what the image build runs.
run_session_entry() {
  local root="${BATS_TEST_TMPDIR}/session-${BATS_TEST_NUMBER}"
  rm -rf "$root"
  mkdir -p "${root}/bin" "${root}/wayland-sessions"
  local cmd
  for cmd in $1; do
    printf '#!/bin/sh\nexit 0\n' >"${root}/bin/${cmd}"
    chmod +x "${root}/bin/${cmd}"
  done
  if [ -n "${2:-}" ]; then
    printf '[Desktop Entry]\nName=Xfce Session\nExec=%s\nType=Application\n' "$2" >"${root}/wayland-sessions/xfce-wayland.desktop"
  fi
  local block
  block="$(awk '/^_xfce_wl_compositor=""/{f=1} /^# The greetd config, gtkgreet/{f=0} f' \
    "${REPO_ROOT}/build_scripts/desktop/xfce-greeter.sh" | sed "s|/usr/share/wayland-sessions|${root}/wayland-sessions|g")"
  PATH="${root}/bin:/usr/bin:/bin" IS_FEDORA=false bash -c "$block"
  grep -h '^Exec=' "${root}/wayland-sessions/"*.desktop
}

# Falsification: delete the compositor pinning from xfce-greeter.sh and the
# packaged `Exec=startxfce4 --wayland` is left as it was: the installed
# yellowfin:xfce logs in and drops back to the greeter (GPU probe run 43783037763).
@test "the packaged EL10 XFCE Wayland session names xfwl4 so startxfce4 does not look for labwc" {
  run run_session_entry "xfwl4" "startxfce4 --wayland"
  [ "$status" -eq 0 ]
  [ "$output" = "Exec=startxfce4 --wayland xfwl4" ]
}

@test "a session entry that already names its compositor is left alone" {
  run run_session_entry "xfwl4 labwc" "startxfce4 --wayland labwc"
  [ "$status" -eq 0 ]
  [ "$output" = "Exec=startxfce4 --wayland labwc" ]
}

@test "the fallback session entry written when nothing is packaged names the compositor too" {
  run run_session_entry "xfwl4"
  [ "$status" -eq 0 ]
  [ "$output" = "Exec=startxfce4 --wayland xfwl4" ]
}

# Falsification: remove the xfwl4 branch from xfce_greetd_greeter_contract and the
# first test below passes (status 0) while the image's login still drops back to the greeter.
@test "a session list that offers bare startxfce4 --wayland fails when xfwl4 is the compositor" {
  run run_contract "greetd gtkgreet cage xfwl4" $'[default_session]\ncommand = "/usr/libexec/tunaos/greetd-session"' "startxfce4 --wayland" $'#!/usr/bin/env bash\nexec cage -s -- gtkgreet'
  [ "$status" -eq 1 ]
  [[ "$output" == *"labwc"* ]]
}

@test "a session list that names xfwl4 passes" {
  run run_contract "greetd gtkgreet cage xfwl4" $'[default_session]\ncommand = "/usr/libexec/tunaos/greetd-session"' "startxfce4 --wayland xfwl4" $'#!/usr/bin/env bash\nexec cage -s -- gtkgreet'
  [ "$status" -eq 0 ]
  [[ "$output" == *CONTRACT_PASS* ]]
}
