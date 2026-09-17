#!/usr/bin/env bats
# /home must not be a dangling symlink in a published image.
#
# ostree-layout.sh makes /home a symlink to var/home and then creates
# /var/home, with a comment stating the reason: "The /var targets must EXIST
# at image-build time, not only in tmpfiles.d." 99-cleanup.sh then runs
# `find /var -mindepth 1 -maxdepth 1 -delete`, which removes it again. On the
# three bases where cleanup runs AFTER layout — Containerfile.arch, .debian
# and .gentoo — the image ships /home pointing at nothing.
#
# tacklebox is the consumer that finds it. Its embedded live baseline runs
# `useradd --create-home` against the published image, and dies:
#
#   >>> [customize] (1/2) baseline.sh
#   useradd: cannot create directory /home
#   Error: live customize for flounder-kde: ... exit status 12
#
# That is flounder:kde and flounder:kde-nvidia on every run since at least
# 2026-09-05. customize-live.sh already fixes it for its own scripts, but runs
# as 2/2 — after the baseline — and tacklebox has no pre-baseline hook.
#
# The two scripts are asserted TOGETHER, because the bug is that they
# disagree: neither is wrong read on its own.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  LAYOUT="${REPO_ROOT}/build_scripts/bootc/ostree-layout.sh"
  CLEANUP="${REPO_ROOT}/build_scripts/99-cleanup.sh"
}

# The alias targets ostree-layout.sh promises. Kept here as the contract both
# scripts answer to, so adding an alias to one and not the other is caught.
ALIAS_TARGETS="var/home var/roothome var/opt var/srv var/mnt var/usrlocal"

@test "ostree-layout creates every /var target its aliases point at" {
  for t in $ALIAS_TARGETS; do
    grep -qF "\${R}/$t" "$LAYOUT" || {
      echo "ostree-layout.sh never creates /$t, but something aliases to it" >&2
      return 1
    }
  done
}

@test "99-cleanup restores the /var targets it wipes" {
  # The wipe is deliberate and stays. What must not stay is the gap between
  # the wipe and the next layer that follows /home.
  run grep -E "find /var -mindepth 1 -maxdepth 1" "$CLEANUP"
  [ "$status" -eq 0 ]
  for t in $ALIAS_TARGETS; do
    run bash -c "grep -E '^mkdir -p .*/$t' '$CLEANUP'"
    [ "$status" -eq 0 ] || {
      echo "99-cleanup.sh wipes /var but never restores /$t" >&2
      return 1
    }
  done
}

@test "the restore happens after the wipe, not before" {
  # Before it, the wipe simply removes it again — the shape this test exists
  # to catch, since a grep for both lines would pass either way.
  wipe=$(grep -n "find /var -mindepth 1 -maxdepth 1" "$CLEANUP" | head -1 | cut -d: -f1)
  restore=$(grep -n "^mkdir -p .*var/home" "$CLEANUP" | head -1 | cut -d: -f1)
  [ -n "$wipe" ] && [ -n "$restore" ]
  [ "$restore" -gt "$wipe" ]
}

# EXECUTED, not read. The failure this guards is a dangling symlink, and a
# grep cannot tell a resolving one from a broken one.
@test "after both scripts run, /home resolves to a real directory" {
  root="$(mktemp -d)"
  mkdir -p "${root}/var" "${root}/usr/lib" "${root}/etc"

  # The part of ostree-layout.sh under test: the alias and its target.
  mkdir -p "${root}/var/home"
  ln -sfnT var/home "${root}/home"
  [ -d "${root}/home" ]   # resolves before cleanup

  # The wipe, verbatim from 99-cleanup.sh.
  find "${root}/var" -mindepth 1 -maxdepth 1 ! -path "${root}/var/cache" -delete 2>/dev/null || true
  [ ! -d "${root}/home" ]  # and now it dangles — the bug, reproduced

  # The restore this change adds.
  mkdir -p "${root}/var/home"
  [ -d "${root}/home" ]

  # What tacklebox's baseline actually does to it.
  run bash -c "cd '${root}' && mkdir -p \"\$(readlink -f '${root}/home')/liveuser\""
  [ "$status" -eq 0 ]
  [ -d "${root}/var/home/liveuser" ]

  rm -rf "$root"
}
