#!/usr/bin/env bats
# The T2 overlay must actually end up on the t2linux kernel.
#
# Every build of bonito:gnome-t2 has died in this script, on both shapes of the
# transaction, with the same message:
#
#   No match for argument 'kernel' in repositories 'copr:…:sharpenedblade:t2linux'
#
# (runs 34613732493, 34750383558, 34756027748 — three buildah attempts each).
# The message names the wrong culprit and has now cost one wrong fix. The COPR
# has carried kernel-7.1.9-200.t2.fc44 since 2026-08-23, and dnf downloads that
# metadata in the very step that then matches nothing. What hides it is the
# fedora-bootc base's repo-level `exclude=kernel*`, which filters the candidate
# set of EVERY repo — the nvidia overlay documented the same filter, and
# recorded that clearing the [main] exclude alone does not lift it.
#
# What these tests pin is the property, not the spelling: the remove must not
# be repo-constrained, the install must be, the exclude filters must be cleared
# at both levels, and the result must be checked. The check is what makes "a
# Fedora kernel silently wins" impossible, which is what the pin reaches for.

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
  install_line="$(_code | grep -A5 'dnf -y install --allowerasing' | tr '\n' ' ')"
  [[ "$install_line" == *"--from-repo"* ]]
  # The id may be held in a variable; whichever way, it must resolve to the COPR.
  [[ "$install_line" == *"sharpenedblade:t2linux"* ]] ||
    _code | grep -qF 'copr:copr.fedorainfracloud.org:sharpenedblade:t2linux'
}

@test "the install clears the base image's exclude filters" {
  # The whole reason the pinned repo appeared to carry no kernel. Repo-level
  # excludes need the glob form; the bare one only clears [main] (see the
  # nvidia overlay, which learned this the same way).
  local install_line
  install_line="$(_code | grep -A5 'dnf -y install --allowerasing' | tr '\n' ' ')"
  [[ "$install_line" == *"--setopt='*.excludepkgs='"* ]]
  [[ "$install_line" == *"--setopt='*.exclude='"* ]]
  [[ "$install_line" == *"--setopt='excludepkgs='"* ]]
  [[ "$install_line" == *"--setopt='exclude='"* ]]
}

@test "the exclude filters actually in force are logged" {
  # If the diagnosis above is ever wrong, the next log says which filters were
  # really set, rather than repeating "No match for argument".
  _code | grep -qF '/etc/yum.repos.d/'
  _code | grep -qE "grep .*(exclude\|excludepkgs)"
}

@test "what the pinned repo offers is logged before the install" {
  # Distinguishes "the repo has no kernel" from "something hid it" in one line.
  _code | grep -qF 'dnf -y repoquery'
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
