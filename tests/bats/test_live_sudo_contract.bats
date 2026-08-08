#!/usr/bin/env bats
# Dev ISOs grant liveuser NOPASSWD sudo. A sudoers file that authorises a
# binary the image does not have is completely silent: the ISO builds, the live
# image boots, and the E2E dies twenty minutes later at `sudo podman load` with
# "bash: line 1: sudo: command not found".
#
# That is tunaOS#953 defect 3. It was fixed on sailfin by naming sudo in
# Containerfile.opensuse, and recurred on grouper because the apt bases never
# got the same line. These tests cover both halves: the assertion that makes it
# loud, and the package lists that satisfy it.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

_code() { grep -v '^[[:space:]]*#' "$1"; }

@test "customize-live.sh refuses to write a sudoers drop-in with no sudo" {
  local script="${REPO_ROOT}/live-iso/common/src/customize-live.sh"
  local code
  code="$(_code "$script")"

  # The guard must exist...
  grep -qF 'command -v sudo' <<<"$code"
  # ...and must stop the ISO build, not warn.
  local guard
  guard="$(sed -n '/command -v sudo/,/fi$/p' "$script")"
  grep -qF 'exit 1' <<<"$guard"

  # And it must come BEFORE the drop-in is written — a guard after the fact
  # still ships the file.
  local guard_line drop_line
  guard_line=$(grep -n 'command -v sudo' "$script" | head -1 | cut -d: -f1)
  # sudoers.d/, not just the basename — an sshd_config drop-in earlier in the
  # file shares the 90-tunaos-live-e2e name.
  drop_line=$(grep -n 'sudoers.d/90-tunaos-live-e2e' "$script" | head -1 | cut -d: -f1)
  [ -n "$guard_line" ]
  [ -n "$drop_line" ]
  [ "$guard_line" -lt "$drop_line" ]
}

@test "every base that does not inherit sudo installs it" {
  # The Fedora/EL bases ship sudo; openSUSE, Debian and Ubuntu do not, and each
  # has to name it. Checked as a list so adding a variant to the tree without
  # it is a failing test rather than a failing matrix cell.
  local f
  for f in Containerfile.opensuse Containerfile.debian Containerfile.ubuntu Containerfile.arch; do
    # Word-boundary match: openSUSE lists it mid-line among a dozen others,
    # the rest give it its own continuation line.
    grep -vE '^[[:space:]]*#' "${REPO_ROOT}/$f" | grep -qE '(^|[[:space:]])sudo([[:space:]]|\\|$)'
  done
}
