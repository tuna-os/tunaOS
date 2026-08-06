#!/usr/bin/env bats
# customize-live.sh writes a NOPASSWD sudoers drop-in for liveuser whenever
# ENABLE_SSHD=1. That drop-in authorises nothing if the image has no sudo, and
# every `sudo` in the E2E guest then dies with "command not found" — which is
# how tunaOS#953 defect 3 presented on sailfin and again on grouper.
#
# The assertion in customize-live.sh turns that into an ISO-build failure, and
# it caught guppy:xfce (LUKS run 31082460289) after a complete, correct image
# build: the Gentoo stage3 tarball ships no sudo and Containerfile.gentoo was
# the last base not to install one.
#
# This is the same one-of-N-Containerfiles shape as openssh in 40-services.sh,
# the pcsc omit line, the erofs driver and zypper_retry. Asserting it per base
# is what stops the (N+1)th.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# Bases that must install sudo explicitly. The rpm bases are excluded because
# their base images already ship it — AlmaLinux/CentOS/Fedora bootc images all
# carry sudo, which is why those cells were green while these were not. If an
# rpm base ever stops shipping it, the customize-live.sh assertion still fires.
EXPLICIT_SUDO_BASES=(
  Containerfile.gentoo
  Containerfile.arch
  Containerfile.opensuse
  Containerfile.debian
  Containerfile.ubuntu
)

@test "the assertion that catches this is still in customize-live.sh" {
  # Without it a missing sudo is silent until something in the guest tries to
  # use it, so the per-base check below would be the only line of defence.
  local f="${REPO_ROOT}/live-iso/common/src/customize-live.sh"
  run grep -q 'command -v sudo' "$f"
  [ "$status" -eq 0 ]
  run grep -q 'this image has no sudo' "$f"
  [ "$status" -eq 0 ]
}

@test "every base that must install sudo does" {
  local f code fail=0
  for f in "${EXPLICIT_SUDO_BASES[@]}"; do
    code="$(sed 's/^[[:space:]]*#.*//' "${REPO_ROOT}/$f")"
    # Gentoo needs the atom; everyone else the bare name. Anchored so a
    # substring like `sudo-rs` or a comment cannot satisfy it.
    if ! grep -qE '(^|[[:space:]])(app-admin/)?sudo([[:space:]]|\\|$)' <<<"$code"; then
      echo "FAIL: ${f} never installs sudo." >&2
      echo "      customize-live.sh grants liveuser NOPASSWD sudo under" >&2
      echo "      ENABLE_SSHD=1 and asserts the binary exists, so this fails" >&2
      echo "      the ISO build — after a complete image build." >&2
      fail=1
    fi
  done
  [ "$fail" -eq 0 ]
}
