#!/usr/bin/env bats
# Every base whose live media has to install must ship podman.
#
# Not a container-tooling nicety: a composefs-native image cannot take
# fisherman's bootcDirect shortcut, so bootc runs inside a container podman
# starts (the SWAP_DISK comment in scripts/iso-e2e.sh is written from a sailfin
# OOM of exactly that process), and customize-live.sh writes
# /etc/containers/storage.conf + a 99- drop-in whose entire purpose is to let
# the live root's podman see the embedded offline store.
#
# guppy shipped app-containers/skopeo — bootc's containers-image-proxy, which
# looks close enough to be mistaken for coverage — and no podman. Every store
# probe answered `sudo: podman: command not found`, so a store recording
# `ghcr.io/tuna-os/guppy:gnome` verbatim read as "image absent" and the cell
# fell through to the SSH image transfer scripts/iso-e2e.sh documents as
# impossible, dying 2h30m in on
#
#   scp: write remote "/home/liveuser/luks-image-guppy-gnome.tar": Failure
#
# guppy:gnome, LUKS run 31134373523. Same one-of-N-Containerfiles shape as sudo
# (tests/bats/test_live_sudo_every_base.bats), flatpak, openssh in
# 40-services.sh and the pcsc omit line — and Gentoo was the last base without
# it for the third time. Asserting it per base is what stops the (N+1)th.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# Bases that must name podman themselves, because they run none of the numbered
# build_scripts. Excluded:
#
#   Containerfile.el10, Containerfile.ubuntu, Containerfile.debian — they source
#   build_scripts/10-base-packages.sh, which installs podman on every branch it
#   has (asserted separately below).
#
#   Containerfile.opensuse — sailfin's live guest demonstrably runs podman: run
#   30730744132 killed it by name (`Out of memory: Killed process 2978
#   (podman)`), so Tumbleweed supplies it through the base image or the
#   enhanced_base pattern rather than an explicit line. If that ever stops being
#   true, the customize-live.sh assertion below turns it into an ISO-build
#   failure instead of an hour-three E2E death.
EXPLICIT_PODMAN_BASES=(
  Containerfile.gentoo
  Containerfile.arch
)

# Bases that get podman from the shared numbered script instead.
SHARED_SCRIPT_BASES=(
  Containerfile.el10
  Containerfile.ubuntu
  Containerfile.debian
)

@test "the assertion that catches this is still in customize-live.sh" {
  # Without it, a missing podman is silent until the install path reaches for
  # it, which on the LUKS matrix is hours later and presents as an scp failure.
  local f="${REPO_ROOT}/live-iso/common/src/customize-live.sh"
  run grep -q 'command -v podman' "$f"
  [ "$status" -eq 0 ]
  run grep -q 'this image has no podman' "$f"
  [ "$status" -eq 0 ]
}

@test "every base that must install podman by name does" {
  local f code fail=0
  for f in "${EXPLICIT_PODMAN_BASES[@]}"; do
    code="$(sed 's/^[[:space:]]*#.*//' "${REPO_ROOT}/$f")"
    # Gentoo needs the atom, Arch the bare name. Anchored so that a substring
    # like `podman-compose`, `podman-docker` or a comment cannot satisfy it.
    if ! grep -qE '(^|[[:space:]])(app-containers/)?podman([[:space:]]|\\|$)' <<<"$code"; then
      echo "FAIL: ${f} never installs podman." >&2
      echo "      A composefs install runs bootc in a container podman starts," >&2
      echo "      and customize-live.sh configures the offline store for one," >&2
      echo "      so the live media cannot install without it." >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}

@test "skopeo alone does not satisfy it" {
  # The exact confusion that produced the bug: skopeo is what bootc's
  # containers-image-proxy shells out to, so a base can look container-capable
  # while being unable to start one.
  local f code
  for f in "${EXPLICIT_PODMAN_BASES[@]}"; do
    code="$(sed 's/^[[:space:]]*#.*//' "${REPO_ROOT}/$f")"
    if grep -qE '(^|[[:space:]])skopeo([[:space:]]|\\|$)' <<<"$code"; then
      run grep -qE '(^|[[:space:]])(app-containers/)?podman([[:space:]]|\\|$)' <<<"$code"
      [ "$status" -eq 0 ]
    fi
  done
}

@test "the shared base-package script installs podman on every branch" {
  # These bases delegate, so the delegate has to hold. One branch omitting it
  # is the same defect with a longer paper trail.
  local f="${REPO_ROOT}/build_scripts/10-base-packages.sh"
  local code
  code="$(sed 's/^[[:space:]]*#.*//' "$f")"
  # apt, hummingbird (dnf --skip-unavailable) and Fedora/EL each have their own
  # package list in this script.
  local count
  count="$(grep -cE '^[[:space:]]*podman[[:space:]]*\\?$' <<<"$code")"
  [ "$count" -ge 3 ]
}

@test "bases that delegate really do source the shared script" {
  # Otherwise the exclusion above is a wish, not a fact.
  local f fail=0
  for f in "${SHARED_SCRIPT_BASES[@]}"; do
    if ! grep -q '10-base-packages.sh' "${REPO_ROOT}/$f"; then
      echo "FAIL: ${f} is listed as getting podman from" >&2
      echo "      build_scripts/10-base-packages.sh but never runs it." >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}
