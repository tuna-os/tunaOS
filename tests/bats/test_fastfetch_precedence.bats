#!/usr/bin/env bats
# verify-fastfetch.sh starts real interactive shells from a skel HOME and runs
# whatever `fastfetch` resolves to there. The stand-in fastfetch follows the
# real search order: --config, then $XDG_CONFIG_HOME, then the system config.
#
# Falsification: put ublue's `alias fastfetch='ublue-fastfetch'` in the skel
# .bashrc and "ublue's alias fails the check" proves the check fails. Put back
# the old `--config /etc/xdg/fastfetch/config.jsonc` alias and "an alias with
# --config fails because the user's config cannot win" proves the same.
setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  CHECK="${REPO_ROOT}/build_scripts/checks/verify-fastfetch.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "${ROOT}/etc/skel" "${ROOT}/usr/share/tunaos" "$BIN"
  printf 'NAME="Grouper"\nPRETTY_NAME="Grouper"\n' >"${ROOT}/etc/os-release"
  printf "TUNAOS_VARIANT='grouper'\nTUNAOS_PROJECT_NAME='TunaOS'\n" >"${ROOT}/usr/share/tunaos/identity.env"
  printf '[ -f ~/.bashrc ] && . ~/.bashrc\n' >"${ROOT}/etc/skel/.bash_profile"
  : >"${ROOT}/etc/skel/.bashrc"
  printf 'system  Grouper  ·  part of TunaOS, built on Ubuntu\n' >"${BIN}/system-config"
  cat >"${BIN}/fastfetch" <<'SH'
#!/bin/sh
cfg=""
while [ $# -gt 0 ]; do
  [ "$1" = --config ] && { cfg="$2"; shift; }
  shift
done
if [ -z "$cfg" ] && [ -f "${XDG_CONFIG_HOME}/fastfetch/config.jsonc" ]; then
  cfg="${XDG_CONFIG_HOME}/fastfetch/config.jsonc"
fi
[ -n "$cfg" ] && [ "$cfg" != /etc/xdg/fastfetch/config.jsonc ] || cfg="$(dirname "$0")/system-config"
cat "$cfg"
SH
  printf '#!/bin/sh\necho "Bluefin  ·  part of Universal Blue"\n' >"${BIN}/ublue-fastfetch"
  chmod +x "${BIN}/fastfetch" "${BIN}/ublue-fastfetch"
}

_check() {
  run env PATH="${BIN}:${PATH}" TUNAOS_BRANDING_ROOT="$ROOT" TUNAOS_FASTFETCH_SHELLS="${1:-bash}" "$CHECK"
}

@test "plain fastfetch passes in login and non-login bash" {
  _check
  [ "$status" -eq 0 ]
  [[ "$output" == *'TUNAOS_FASTFETCH_OK shells=bash system="system Grouper · part of TunaOS, built on Ubuntu"'* ]]
}

@test "ublue's alias fails the check" {
  echo "alias fastfetch='ublue-fastfetch'" >"${ROOT}/etc/skel/.bashrc"
  _check
  [ "$status" -eq 1 ]
  [[ "$output" == *'bash -lic: output lacks "part of TunaOS"'* ]]
  [[ "$output" == *"bash -ic: output names an upstream project"* ]]
}

@test "an alias with --config fails because the user's config cannot win" {
  # The zz-tunaos-fastfetch.sh alias every image carried until this check.
  echo "alias fastfetch='fastfetch --config /etc/xdg/fastfetch/config.jsonc'" >"${ROOT}/etc/skel/.bashrc"
  _check
  [ "$status" -eq 1 ]
  [[ "$output" == *"bash -lic: a user's ~/.config/fastfetch does not win"* ]]
}

@test "a system line without PRETTY_NAME fails" {
  printf 'system  Ubuntu 26.04 LTS  ·  part of TunaOS\n' >"${BIN}/system-config"
  _check
  [ "$status" -eq 1 ]
  [[ "$output" == *"system line lacks PRETTY_NAME 'Grouper'"* ]]
}

@test "zsh and fish get the same probe when installed" {
  command -v zsh >/dev/null && command -v fish >/dev/null || skip "zsh and fish required"
  _check "bash zsh fish"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_FASTFETCH_OK shells=bash,zsh,fish"* ]]
}

@test "an image without fastfetch says so and passes" {
  run env PATH="/usr/bin:/bin" TUNAOS_BRANDING_ROOT="$ROOT" "$CHECK"
  command -v fastfetch >/dev/null && skip "this host has fastfetch in /usr/bin"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_FASTFETCH_OK status=not-installed"* ]]
}

@test "90-image-info.sh deletes ublue's aliases outside the identity branch and runs the check" {
  local script="${REPO_ROOT}/build_scripts/90-image-info.sh" rm_line if_line check_line
  rm_line="$(grep -n '^rm -f /etc/profile.d/ublue-fastfetch.sh' "$script" | cut -d: -f1)"
  if_line="$(grep -n '^if \[\[ -n "${IDENTITY_ROW}" \]\]; then' "$script" | cut -d: -f1)"
  check_line="$(grep -n '^	/usr/libexec/tunaos/verify-fastfetch$' "$script" | cut -d: -f1)"
  [ -n "$rm_line" ] && [ -n "$if_line" ] && [ -n "$check_line" ]
  [ "$rm_line" -lt "$if_line" ] && [ "$if_line" -lt "$check_line" ]
  grep -q '/usr/share/fish/vendor_conf.d/ublue-fastfetch.fish' "$script"
  grep -q '/usr/bin/ublue-fastfetch' "$script"
}

@test "our shell snippets alias neofetch only, never fastfetch itself" {
  local f
  for f in etc/profile.d/tunaos-fastfetch.sh usr/share/fish/vendor_conf.d/tunaos-fastfetch.fish; do
    run grep -Ev '^[[:space:]]*#' "${REPO_ROOT}/system_files/${f}"
    [[ "$output" == *"alias neofetch"* ]]
    [[ "$output" != *"alias fastfetch"* && "$output" != *"--config"* ]]
  done
}
