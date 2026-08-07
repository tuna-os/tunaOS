#!/usr/bin/env bats
# Transient-failure retry must not be a dnf-only privilege.
#
# sailfin:niri died in LUKS run 31089226102 with nothing wrong in the tree:
# Tumbleweed rotated a snapshot mid-build, so repomd.xml pointed at a
# primary.xml the mirror had already dropped. zypper treats a failed repository
# refresh as a WARNING, skips that repository, and carries on — so the build ran
# on with repo-oss silently absent and died somewhere unrelated:
#
#   Warning: Skipping repository 'openSUSE-Tumbleweed-Oss' because of the above error.
#   Package 'systemd-network' not found.
#
# dnf has had dnf_retry for this class since #1015. The zypper path never got
# one — the same one-of-N-package-managers gap as openssh in 40-services.sh and
# the pcsc omit line on Debian.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
LIB="${REPO_ROOT}/build_scripts/lib.sh"

@test "the zypper install path retries" {
  run grep -qE '^\s*zypper_retry --non-interactive in ' "$LIB"
  [ "$status" -eq 0 ]
  # ...and no bare `zypper ... in` slipped back alongside it.
  run grep -nE '^\s*zypper --non-interactive in ' "$LIB"
  [ "$status" -ne 0 ]
}

@test "the zypper refresh path retries" {
  # The stale-repomd case is a REFRESH failure, so retrying only the install
  # would leave the actual defect uncovered.
  run grep -qE 'zypper\) zypper_retry .* refresh' "$LIB"
  [ "$status" -eq 0 ]
}

@test "zypper_retry propagates a real failure instead of masking it" {
  # An unresolvable package must still fail, with zypper's own exit code —
  # a retry wrapper that swallows errors is worse than none.
  run bash -c '
    set -uo pipefail
    ZYPPER_RETRY_ATTEMPTS=2
    zypper() { [[ "$*" == *refresh* ]] && return 0; return 104; }
    eval "$(sed -n "/^zypper_retry() {/,/^}/p" '"$LIB"')"
    zypper_retry --non-interactive in nosuchpkg >/dev/null 2>&1
    echo $?
  '
  [ "$status" -eq 0 ]
  [ "$output" -eq 104 ]
}

@test "zypper_retry succeeds once the transient failure clears" {
  run bash -c '
    set -uo pipefail
    ZYPPER_RETRY_ATTEMPTS=4
    n=0
    zypper() { [[ "$*" == *refresh* ]] && return 0; n=$((n+1)); (( n >= 2 )) && return 0; return 4; }
    eval "$(sed -n "/^zypper_retry() {/,/^}/p" '"$LIB"')"
    zypper_retry --non-interactive in foo >/dev/null 2>&1
    echo $?
  '
  [ "$status" -eq 0 ]
  [ "$output" -eq 0 ]
}
