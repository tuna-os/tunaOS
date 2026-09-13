#!/usr/bin/env bats
# The T2 overlay must actually end up on the t2linux kernel.
#
# Four builds of bonito:gnome-t2 died in this script before dnf named the
# cause, in run 34762701445:
#
#   Argument 'kernel-7.1.9-200.t2.fc44' matches only packages excluded
#   by versionlock.
#
# 10-base-packages.sh locks the INSTALLED Fedora kernel (`dnf versionlock add
# kernel …`), pinning 7.2.4-200.fc44 and excluding every other version. Three
# earlier readings of the same obstacle were all wrong, and each is worth
# naming so nobody re-derives it: it is not `--from-repo` constraining the
# remove spec (#2494), not `--from-repo` being broken because repoquery found
# what install could not (#2497 — repoquery simply ignores versionlock), and
# not the base image's exclude filters (#2495 — those really are "(none)";
# versionlock keeps a list of its own that the probe never read).
#
# The two kernel swaps already here never met the lock: nvidia's bypasses dnf
# with `rpm -ivh`, asahi's installs `kernel-16k`, a name the list does not
# carry. t2 installs packages named exactly `kernel`, so it is the first one
# the lock bites.
#
# What these tests pin is the property, not the spelling: the lock is released
# before the swap and re-applied after it, the EVR comes from the COPR, and the
# result is asserted rather than assumed.

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

@test "the stock kernel's versionlock is released before the install" {
  # Without this the install matches nothing: every t2 version is excluded by
  # the lock 10-base-packages.sh puts on the installed Fedora kernel.
  _code | grep -qE 'dnf versionlock delete .*kernel'
  # Ordered: delete must come before the install, or it changes nothing.
  local del_at ins_at
  del_at="$(_code | grep -n 'versionlock delete' | head -1 | cut -d: -f1)"
  ins_at="$(_code | grep -n 'dnf -y install --allowerasing' | head -1 | cut -d: -f1)"
  [ -n "$del_at" ] && [ -n "$ins_at" ]
  [ "$del_at" -lt "$ins_at" ]
}

@test "every name the base script locks is released" {
  # A straggler keeps its hold and the swap fails on that package alone.
  local base="${REPO_ROOT}/build_scripts/10-base-packages.sh"
  local locked
  locked="$(grep -o 'dnf versionlock add kernel[^|]*' "$base" | head -1)"
  [ -n "$locked" ]
  # Joined: the delete spans continuation lines, and a per-line grep reports a
  # released package as missing (it did, for kernel-modules).
  local delete_stmt
  delete_stmt="$(_code | grep -A3 'versionlock delete' | tr '\n\t' '  ' | tr -s ' ')"
  [ -n "$delete_stmt" ]
  local pkg
  for pkg in $(sed 's/dnf versionlock add //' <<<"$locked"); do
    case "$pkg" in
    kernel*)
      [[ " $delete_stmt " == *" $pkg "* ]] ||
        { echo "not released: $pkg"; return 1; }
      ;;
    esac
  done
}

@test "the lock is re-applied to the kernel we installed" {
  # Leaving it unlocked lets a later transaction pull a Fedora kernel back
  # over this one — 10-kernel-swap.sh re-locks after its swap for the same
  # reason.
  local add_at ins_at
  add_at="$(_code | grep -n 'versionlock add' | tail -1 | cut -d: -f1)"
  ins_at="$(_code | grep -n 'dnf -y install --allowerasing' | head -1 | cut -d: -f1)"
  [ -n "$add_at" ] && [ -n "$ins_at" ]
  [ "$add_at" -gt "$ins_at" ]
}

@test "the versionlock list is logged" {
  # The probe that would have found this on day one: dnf.conf and the .repo
  # files are not the only place a package can be filtered out.
  _code | grep -qF 'dnf versionlock list'
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
