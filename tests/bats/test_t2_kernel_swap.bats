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

@test "the install no longer asks --from-repo to carry the pin" {
  # Measured, not assumed: run 34760267199 ran repoquery --repo and install
  # --from-repo in the same job, seconds apart, with the same id and options.
  # The repoquery listed kernel-7.1.9-200.t2.fc44; the install said "No match
  # for argument 'kernel'" and loaded no repository at all.
  # Joined, because the old form put --from-repo on its own continuation
  # line and a single-line grep would pass against it for the wrong reason.
  local install_line
  install_line="$(_code | grep -A6 'dnf -y install --allowerasing' | tr '\n' ' ')"
  [ -n "$install_line" ]
  [[ "$install_line" != *"--from-repo"* ]]
}

@test "the pin lives in the argument, as an exact EVR" {
  # Fedora ships 7.2.4-200.fc44 and the COPR 7.1.9-200.t2.fc44, so an exact
  # EVR can only resolve to the t2 build — a pin nothing can reinterpret.
  local install_line
  install_line="$(_code | grep -A6 'dnf -y install --allowerasing' | tr '\n' ' ')"
  [[ "$install_line" == *'"kernel-${_t2_evr}"'* ]]
  [[ "$install_line" == *'"kernel-core-${_t2_evr}"'* ]]
  [[ "$install_line" == *'"kernel-modules-${_t2_evr}"'* ]]
  [[ "$install_line" == *'"kernel-modules-core-${_t2_evr}"'* ]]
}

@test "the EVR comes from the COPR and must carry the t2 dist tag" {
  # Reading the version from the repo is the whole mechanism, so a repo that
  # offers no .t2. kernel must stop the build rather than install whatever
  # sorted last.
  _code | grep -qF 'dnf -y repoquery --repo="${_T2_REPO}"'
  _code | grep -qE "grep -E '\\\\.t2\\\\.'"
  _code | grep -qF 'ERROR: the t2linux repo offers no kernel build tagged .t2.'
}

@test "the exclude filters actually in force are logged" {
  # This probe is what disproved the exclude theory (run 34760267199 printed
  # "(none)"). It stays: it costs one line and it is how the next wrong
  # diagnosis gets caught before it ships.
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
