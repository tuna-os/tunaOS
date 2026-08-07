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
# and a fixture root (what /etc/greetd/config.toml says). require_command is
# redefined with the script's real semantics: missing command → exit 1.
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

@test "greetd with gtkgreet, cage and a gtkgreet config passes" {
  run run_contract "greetd gtkgreet cage" 'command = "cage -s -- gtkgreet -l -s /etc/greetd/gtkgreet.css"'
  [ "$status" -eq 0 ]
  [[ "$output" == *CONTRACT_PASS* ]]
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
