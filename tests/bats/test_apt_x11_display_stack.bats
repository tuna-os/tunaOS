#!/usr/bin/env bats
# An X11 login stack on apt must carry its own X server. pkg_install runs
# apt with --no-install-recommends, and lightdm only *Recommends* an X
# server — nothing on the xfce or pantheon apt lists hard-depends one. Both
# images shipped without /usr/lib/xorg/Xorg; lightdm's seat then has no
# display server to spawn and the daemon exits 1 within a second of every
# start, logging only to its own /var/log/lightdm/lightdm.log — journal and
# serial show a bare crash loop (LUKS runs 31215925331 grouper:xfce and
# 31215923156 gurnard:pantheon; root cause reproduced and bisected on
# ubuntu:resolute by installing the exact list, watching the identical
# instant exit 1, then adding the X server and watching the seat get past
# display-server creation). accountsservice is pinned for the same reason
# one notch down: a lightdm Recommends every greeter queries for the user
# list, whose absence is the "Error getting user list from
# org.freedesktop.Accounts" warning that was the only journal evidence the
# xfce cell produced.
#
# These pins are comment-stripped: commenting a package out fails the test
# the same as deleting it.

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
XFCE_SH="${REPO_ROOT}/build_scripts/desktop/xfce.sh"
PANTHEON_YAML="${REPO_ROOT}/manifests/desktops/pantheon.yaml"

# The apt branch of xfce.sh, comments stripped. Everything from the apt
# guard to its closing `fi` — the pkg_install list lives inside it.
xfce_apt_branch() {
  awk '/PKG_MGR.*==.*"apt"/,/^\tfi$/' "$XFCE_SH" | grep -v '^\s*#'
}

@test "xfce.sh apt branch installs an X server alongside lightdm" {
  run xfce_apt_branch
  [ "$status" -eq 0 ]
  [[ "$output" == *"lightdm"* ]]
  [[ "$output" == *"xserver-xorg"* ]]
}

@test "xfce.sh apt branch installs accountsservice for the greeter user list" {
  run xfce_apt_branch
  [ "$status" -eq 0 ]
  [[ "$output" == *"accountsservice"* ]]
}

@test "xfce.sh apt X server rides the fatal pkg_install, not a best-effort list" {
  # install_available demotes a package to a wishlist entry; a repo
  # regression would then ship the crash-looping image again with a green
  # build. The X server must sit in the same hard pkg_install as lightdm.
  run bash -c "
    awk '/PKG_MGR.*==.*\"apt\"/,/^\tfi$/' '$XFCE_SH' \
      | grep -v '^\s*#' \
      | awk '/pkg_install/,/^\$/' \
      | grep -c 'xserver-xorg\|accountsservice\|lightdm'
  "
  [ "$status" -eq 0 ]
  [ "$output" -ge 3 ]
}

# Non-comment package entries of pantheon.yaml's apt list.
pantheon_packages() {
  grep -v '^\s*#' "$PANTHEON_YAML" | grep '^\s*- '
}

@test "pantheon.yaml installs an X server alongside lightdm" {
  run pantheon_packages
  [ "$status" -eq 0 ]
  [[ "$output" == *"- lightdm"* ]]
  [[ "$output" == *"- xserver-xorg"* ]]
}

@test "pantheon.yaml installs accountsservice for the greeter user list" {
  run pantheon_packages
  [ "$status" -eq 0 ]
  [[ "$output" == *"- accountsservice"* ]]
}
