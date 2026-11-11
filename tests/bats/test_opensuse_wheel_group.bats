#!/usr/bin/env bats
# accountsservice puts every administrator account in its admin group, which
# defaults to wheel on non-Debian distros, and openSUSE's package neither sets
# another group nor requires one. Tumbleweed creates wheel only when
# system-group-wheel is installed. Without it GNOME Initial Setup's first
# account fails "Failed to run useradd: Child process exited with code 6"
# (group does not exist): sailfin:gnome, iso-builder run 42920148544.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "openSUSE base installs system-group-wheel" {
  code="$(sed 's/^[[:space:]]*#.*//' "${REPO_ROOT}/Containerfile.opensuse")"
  run grep -qE '(^|[[:space:]])system-group-wheel([[:space:]]|\\|$)' <<<"$code"
  [ "$status" -eq 0 ]
}

@test "openSUSE base fails the build when wheel is missing" {
  code="$(sed 's/^[[:space:]]*#.*//' "${REPO_ROOT}/Containerfile.opensuse")"
  run grep -qE 'getent group wheel' <<<"$code"
  [ "$status" -eq 0 ]
}
