#!/usr/bin/env bats
# A built image ships no /etc/hostname with a name in it (tunaOS#4865). The
# published grouper image shipped "localhost.localdomain" from its
# ubuntu:resolute base, so DEFAULT_HOSTNAME never applied.
#
# Falsification: make verify-image-hostname.sh treat every `podman cp` error
# as "absent" and the storage-error case passes. Drop --no-hostname from
# either build in build-image-inner.sh, or the check after either build, and
# the wiring cases fail.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CHECK="${REPO_ROOT}/scripts/verify-image-hostname.sh"
ENGINE="${REPO_ROOT}/scripts/build-image-inner.sh"

setup() {
  STUB="$(mktemp -d)"
  # podman stub: FAKE_ETC_HOSTNAME is the image's /etc/hostname, or
  # __absent__ / __broken__ for podman 4.9's two failure shapes.
  cat >"${STUB}/podman" <<'EOF'
#!/usr/bin/env bash
case "$1" in
create) echo ctr0 ;;
cp)
  case "$FAKE_ETC_HOSTNAME" in
  __absent__)
    echo 'Error: "/etc/hostname" could not be found on container ctr0: no such file or directory' >&2
    exit 125 ;;
  __broken__)
    echo 'Error: mounting storage for container ctr0: input/output error' >&2
    exit 125 ;;
  *) printf '%s' "$FAKE_ETC_HOSTNAME" >"$3" ;;
  esac ;;
rm) ;;
esac
EOF
  chmod +x "${STUB}/podman"
  export PATH="${STUB}:${PATH}"
}

teardown() { rm -rf "$STUB"; }

@test "the published grouper image's localhost.localdomain fails" {
  FAKE_ETC_HOSTNAME=$'localhost.localdomain\n' run "$CHECK" ghcr.io/tuna-os/grouper:gnome
  [ "$status" -eq 1 ]
  [[ "$output" == *"TUNAOS_IMAGE_HOSTNAME_FAIL image=ghcr.io/tuna-os/grouper:gnome hostname=localhost.localdomain"* ]]
}

@test "any name fails, not only a fallback one" {
  FAKE_ETC_HOSTNAME=$'grouper\n' run "$CHECK" img
  [ "$status" -eq 1 ]
  [[ "$output" == *"hostname=grouper"* ]]
}

@test "an image without /etc/hostname passes" {
  FAKE_ETC_HOSTNAME=__absent__ run "$CHECK" img
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_IMAGE_HOSTNAME_OK image=img etc_hostname=absent"* ]]
}

@test "an empty or comment-only file passes (buildah's RUN leftover)" {
  FAKE_ETC_HOSTNAME='' run "$CHECK" img
  [ "$status" -eq 0 ]
  [[ "$output" == *"etc_hostname=empty"* ]]
  FAKE_ETC_HOSTNAME=$'# set by the installer\n\n' run "$CHECK" img
  [ "$status" -eq 0 ]
}

@test "a podman error other than a missing file fails" {
  FAKE_ETC_HOSTNAME=__broken__ run "$CHECK" img
  [ "$status" -eq 1 ]
  [[ "$output" == *"input/output error"* ]]
  [[ "$output" == *"TUNAOS_IMAGE_HOSTNAME_FAIL"* ]]
}

@test "both builds in build-image-inner.sh run with --no-hostname" {
  # Without it, 90-image-info.sh's rm hits the builder's bind mount (EBUSY).
  run grep -c -- '--no-hostname \\$' "$ENGINE"
  [ "$output" -eq 2 ]
  run awk '/^build_primary_image\(\) \{/,/^\}/' "$ENGINE"
  [[ "$output" == *"--no-hostname"* ]]
  run awk '/^\$\{BUILDER\} build \\$/{f=1} f && /--no-hostname/{print "final"} /--file "Containerfile.final"/{f=0}' "$ENGINE"
  [ "$output" = final ]
}

@test "build-image-inner.sh checks the image after each build" {
  # The pre-chunk image before the PR builds' early exit, the final one after
  # Containerfile.final.
  run awk '/verify-image-hostname.sh "\$\{PRE_CHUNK_TAG\}"/{print "check"} /SKIP_RECHUNK=1 — tagging/{print "skip"}' "$ENGINE"
  [ "${lines[0]}" = check ]
  [ "${lines[1]}" = skip ]
  run awk '/--file "Containerfile.final"/{f=1} f && /verify-image-hostname.sh "\$\{IMAGE_TAG\}"/{print "ok"}' "$ENGINE"
  [ "$output" = ok ]
}

@test "90-image-info.sh removes /etc/hostname unless the builder mounted it" {
  run grep -A2 "grep -qs ' /etc/hostname ' /proc/self/mountinfo" "${REPO_ROOT}/build_scripts/90-image-info.sh"
  [[ "$output" == *"rm -f /etc/hostname"* ]]
}
