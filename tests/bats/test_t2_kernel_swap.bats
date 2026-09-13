#!/usr/bin/env bats
# The T2 overlay must actually end up on the t2linux kernel.
#
# `dnf swap --from-repo=X A B` constrains BOTH specs to X. The remove spec is
# the INSTALLED kernel, which does not come from the COPR, so the old one-liner
#
#   dnf -y swap --from-repo="copr:…:sharpenedblade:t2linux" kernel kernel
#
# died before the install side was ever considered:
#
#   No match for argument 'kernel' in repositories 'copr:…:sharpenedblade:t2linux'
#
# three attempts, every run (bonito:gnome-t2, runs 34613732493, 34750383558).
# The install side was never the problem — the enabled chroot is fedora-44 and
# that chroot carries kernel-7.1.9-200.t2.fc44.
#
# What these pin is the property, not the spelling: the remove must not be
# repo-constrained, the install must be, and the result must be checked. The
# check is what makes "a Fedora kernel silently wins" impossible, which is what
# the --from-repo pin was reaching for.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/overlay/t2.sh"

# Prose in this repo quotes the very commands these tests search for, so strip
# comments before matching or a deleted command still "passes".
_code() { grep -v '^[[:space:]]*#' "$SCRIPT"; }

@test "the repo-constrained swap that cannot resolve is gone" {
  ! _code | grep -qE 'dnf .*swap .*--from-repo'
}

@test "the kernel removal is not constrained to the COPR" {
  # The installed kernel comes from Fedora; constraining the remove to the
  # COPR is exactly what matched nothing.
  local remove_line
  remove_line="$(_code | grep -A2 'dnf -y remove' | tr '\n' ' ')"
  [ -n "$remove_line" ]
  [[ "$remove_line" != *"--from-repo"* ]]
}

@test "the kernel install IS constrained to the t2linux COPR" {
  local install_line
  install_line="$(_code | grep -A3 'dnf -y install --allowerasing' | tr '\n' ' ')"
  [[ "$install_line" == *"--from-repo"* ]]
  [[ "$install_line" == *"sharpenedblade:t2linux"* ]]
}

@test "the result is asserted, not assumed" {
  # A flag whose scope surprised us is not a guarantee; a check on the
  # installed package is.
  _code | grep -qF "rpm -q kernel"
  _code | grep -qF '*.t2.*'
  _code | grep -qF 'ERROR: installed kernel is not the t2linux build'
}

@test "the swap logs what was installed before it runs" {
  # So a wrong assumption shows up as a package list in the log rather than as
  # a bare "No match for argument" that says nothing about the image.
  _code | grep -qF "rpm -qa 'kernel*'"
}

@test "t2.sh passes shellcheck" {
  if ! command -v shellcheck &>/dev/null; then skip "shellcheck not installed"; fi
  run shellcheck --severity=error --exclude=SC1091 "$SCRIPT"
  [ "$status" -eq 0 ]
}
