#!/usr/bin/env bats
# BATS tests for the live-ISO cosmic-greeter mask (tunaOS#678).
#
# live-iso/common/src/desktop-cosmic.sh unconditionally repoints
# display-manager.service at greetd.service so the LIVE session autologins
# straight into COSMIC via our own /etc/greetd/config.toml. That is
# necessary but not sufficient on EL10 (yellowfin, skipjack, bonito, ...):
# their cosmic-greeter package ships cosmic-greeter.service with
# `[Install] WantedBy=graphical.target` and no `Alias=display-manager.service`
# (see build_scripts/desktop/configure-desktop-runtime.sh's cosmic case for
# the full story of why Debian/Ubuntu and EL10 differ here). With no alias to
# override, re-pointing display-manager.service does nothing to it: it is
# independently pulled in by graphical.target and starts anyway, alongside
# our greetd.service, racing it for vt1.
#
# CONFIRMED at runtime by installer-smoke run 31229915708 (yellowfin:cosmic):
# both units started in the same second, cosmic-greeter.service won vt1, and
# every screenshot across a full 9-step installer walkthrough showed its
# login prompt for liveuser — crash-looping (check_children: greeter exited
# without creating a session) and re-showing the password field on every
# restart — never the desktop, never the installer. The "compositor is
# running" check upstream of the walkthrough still passed throughout, because
# cosmic-greeter renders its own login UI via cosmic-comp too, so `pgrep -x
# cosmic-comp` cannot tell the greeter and a real session apart.
#
# This is the LIVE-ISO half of the problem; it is deliberately a different
# script and a different mechanism from tests/bats/test_cosmic_display_manager.bats
# (which covers the INSTALLED system's DM choice at image-build time, made by
# build_scripts/desktop/configure-desktop-runtime.sh and
# build_scripts/desktop/install-desktop.sh). The live ISO always wants direct
# autologin, on every base — masking cosmic-greeter.service here is correct
# regardless of which DM that installed-system logic chose, because
# desktop-cosmic.sh already overrides the DM choice unconditionally for the
# live session.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/live-iso/common/src/desktop-cosmic.sh"

@test "desktop-cosmic.sh: exists" {
  run test -f "$SCRIPT"
  [ "$status" -eq 0 ]
}

@test "desktop-cosmic.sh: has valid bash syntax" {
  run bash -n "$SCRIPT"
  [ "$status" -eq 0 ]
}

@test "desktop-cosmic.sh: masks cosmic-greeter.service" {
  run grep -q 'systemctl mask cosmic-greeter.service' "$SCRIPT"
  [ "$status" -eq 0 ]
}

@test "desktop-cosmic.sh: masks, not merely disables, cosmic-greeter.service" {
  # disable only removes the WantedBy symlink and still lets something else
  # start the unit by name later in the same pipeline (e.g. a subsequent
  # systemctl enable/start elsewhere); mask hard-links it to /dev/null so
  # nothing can bring it back up. A regression to 'disable' would reopen the
  # exact race this test suite exists to catch.
  run grep -qE 'systemctl (disable|stop) cosmic-greeter' "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "desktop-cosmic.sh: has an offline symlink fallback if systemctl mask is unavailable" {
  # mkdir -p /etc/systemd/system already exists via other systemctl calls in
  # this same live_customize container; the manual fallback must target the
  # same well-known mask idiom (symlink to /dev/null) systemctl itself uses.
  run grep -qE "ln -sf /dev/null /etc/systemd/system/cosmic-greeter\.service" "$SCRIPT"
  [ "$status" -eq 0 ]
}

@test "desktop-cosmic.sh: still enables our own greetd.service (the mask is additive)" {
  # A future edit that swaps the fix in the wrong direction — masking
  # cosmic-greeter without keeping greetd enabled — would leave the live ISO
  # with no display manager running at all.
  run grep -q 'systemctl enable greetd.service' "$SCRIPT"
  [ "$status" -eq 0 ]
}

@test "desktop-cosmic.sh: passes shellcheck" {
  if ! command -v shellcheck >/dev/null 2>&1; then
    skip "shellcheck not installed"
  fi
  run shellcheck --exclude=SC1091 "$SCRIPT"
  [ "$status" -eq 0 ]
}
