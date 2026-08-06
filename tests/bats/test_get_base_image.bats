#!/usr/bin/env bats
# Unit tests for scripts/get-base-image.sh
#
# Tests variant → base image URI mapping. This script is sourced
# by the build engine (build-image-inner.sh) and every build variant depends on it.
#
# Run: bats tests/bats/test_get_base_image.bats

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"

setup() {
  SCRIPT="${REPO_ROOT}/scripts/get-base-image.sh"
}

# ── Variant mapping tests ────────────────────────────────────────────────────

@test "yellowfin → almalinux-bootc:10-kitten" {
  run bash "$SCRIPT" yellowfin
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/almalinuxorg/almalinux-bootc:10-kitten" ]
}

@test "albacore → almalinux-bootc:10" {
  run bash "$SCRIPT" albacore
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/almalinuxorg/almalinux-bootc:10" ]
}

@test "skipjack → centos-bootc:stream10" {
  run bash "$SCRIPT" skipjack
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/centos-bootc/centos-bootc:stream10" ]
}

@test "bonito → fedora-bootc:44" {
  run bash "$SCRIPT" bonito
  [ "$status" -eq 0 ]
  [ "$output" = "quay.io/fedora/fedora-bootc:44" ]
}

# ── Agreement with build-config.yml ──────────────────────────────────────────

@test "every variant in build-config.yml resolves to that config's base_image" {
  # This script used to hardcode its own copy of the mapping, and the two
  # drifted with nothing to catch it: build-config said bonito was on
  # fedora-bootc:44 while the script said :43, guppy was digest-pinned in the
  # config and floating on :latest in the script, and gurnard was missing
  # outright (#1014 — "Unknown variant: gurnard").
  #
  # The per-variant tests above pin specific strings, which is what let the
  # drift live: updating build-config.yml did not fail them. This one compares
  # against the config itself, so any new variant is covered the day it is
  # added and no edit to either file can silently disagree again.
  local variants
  variants="$(yq -r '.variants[].id' "${REPO_ROOT}/.github/build-config.yml")"
  [ -n "$variants" ]

  local v want got checked=0
  while read -r v; do
    [ -n "$v" ] || continue
    want="$(yq -r ".variants[] | select(.id == \"${v}\") | .base_image" \
      "${REPO_ROOT}/.github/build-config.yml")"
    [ "$want" != "null" ] || continue
    got="$(bash "$SCRIPT" "$v")"
    if [ "$got" != "$want" ]; then
      echo "FAIL: ${v}: script says '${got}', build-config.yml says '${want}'" >&2
      return 1
    fi
    checked=$((checked + 1))
  done <<<"$variants"

  # Guard the guard: a parse that silently yielded nothing would pass the loop.
  [ "$checked" -ge 10 ]
}

@test "gurnard resolves (regression: #1014 'Unknown variant: gurnard')" {
  run bash "$SCRIPT" gurnard
  [ "$status" -eq 0 ]
  [ "$output" = "docker.io/library/ubuntu:noble" ]
}

@test "redfin resolves though it is absent from build-config.yml" {
  # redfin needs an RHSM subscription to pull, so it is deliberately kept off
  # the public matrix and out of build-config.yml. Reading the config must not
  # drop it — `just corral-build` / `just lifecycle-test` still build it.
  run bash "$SCRIPT" redfin
  [ "$status" -eq 0 ]
  [ "$output" = "registry.redhat.io/rhel10/rhel-bootc:latest" ]
}

@test "marlin arm64 override survives config lookup" {
  # docker.io/archlinux is x86_64-only; arm64 comes from build-archlinuxarm-base.yml.
  run bash "$SCRIPT" marlin linux/arm64
  [ "$status" -eq 0 ]
  [ "$output" = "ghcr.io/tuna-os/archlinuxarm:latest" ]
  # ...and does not leak into other variants or other platforms.
  run bash "$SCRIPT" marlin linux/amd64
  [ "$output" = "docker.io/archlinux/archlinux:latest" ]
}

# ── Error handling ────────────────────────────────────────────────────────────

@test "unknown variant exits 1" {
  run bash "$SCRIPT" nonexistent_variant
  [ "$status" -eq 1 ]
}

@test "unknown variant writes to stderr" {
  run bash "$SCRIPT" not_a_real_variant
  [[ "$output" == *"Unknown variant"* ]]
}

@test "no argument exits 1" {
  run bash "$SCRIPT"
  [ "$status" -eq 1 ]
}

# ── Output format ─────────────────────────────────────────────────────────────

@test "output is a single line (no trailing whitespace)" {
  run bash "$SCRIPT" yellowfin
  [ "$status" -eq 0 ]
  # Output should be exactly one line
  [ "$(echo "$output" | wc -l)" -eq 1 ]
}

@test "all references start with registry prefix" {
  for variant in yellowfin albacore skipjack bonito redfin; do
    run bash "$SCRIPT" "$variant"
    [ "$status" -eq 0 ]
    [[ "$output" =~ ^(quay\.io|registry\.redhat\.io) ]]
  done
}

# ── Containerfile target coverage ────────────────────────────────────────────

@test "every build_image flavor has a matching Containerfile target" {
  # Three separate issues were the same missing-alias bug, each found only
  # when a LUKS E2E cell burned a full runner to report
  # `The target "<flavor>" was not found in the provided Dockerfile`:
  #   sailfin:cosmic  — manifest had a zypper section, stage never added (#1012)
  #   guppy:xfce      — manifest had an emerge section, stage never added (#1012)
  #   gurnard:*       — resolved to Containerfile.el10 entirely (#1014)
  #
  # build-config.yml declaring build_image: true is the promise; a `FROM ... AS
  # <flavor>` line is what keeps it. Check them against each other statically
  # so the next one costs a test run rather than a QEMU boot.
  local config="${REPO_ROOT}/.github/build-config.yml"
  local variant flavor cf target missing=""

  while read -r variant; do
    [ -n "$variant" ] || continue
    while read -r flavor; do
      [ -n "$flavor" ] || continue
      # resolve-flavor.sh owns the flavor → (Containerfile, target) mapping,
      # including the overlay flavors that legitimately have no stage of their
      # own (-nvidia, -hwe, -cachyos, -asahi all build from Containerfile.overlay).
      eval "$(bash "${REPO_ROOT}/scripts/resolve-flavor.sh" "$variant" "$flavor" 0)"
      cf="${REPO_ROOT}/${CONTAINERFILE}"
      target="${DESKTOP_FLAVOR}"
      [ -f "$cf" ] || { missing="${missing}\n${variant}:${flavor} -> ${CONTAINERFILE} (no such file)"; continue; }
      grep -qE "^FROM .* AS ${target}\$" "$cf" ||
        missing="${missing}\n${variant}:${flavor} -> ${CONTAINERFILE} has no 'AS ${target}'"
    done < <(yq -r ".variants[] | select(.id == \"${variant}\") | .flavors[] | select(.build_image == true) | .id" "$config")
  done < <(yq -r '.variants[].id' "$config")

  if [ -n "$missing" ]; then
    echo -e "Declared build_image: true with no Containerfile target:${missing}" >&2
    return 1
  fi
}

@test "every Containerfile whose stages use install-desktop.sh ships manifests" {
  # install-desktop.sh reads /run/context/manifests/desktops/<flavor>.yaml.
  # Containerfile.ubuntu's desktop stages each called their own
  # build_scripts/desktop script and never needed a manifest, so its context
  # stage never copied them — until pantheon (manifest-only) was added and
  # gurnard died with "No manifest found" (#1014). A Containerfile that calls
  # the manifest-driven installer must carry the manifests.
  local cf missing=""
  for cf in "${REPO_ROOT}"/Containerfile.*; do
    grep -q 'install-desktop\.sh' "$cf" 2>/dev/null || continue
    grep -q '^COPY manifests' "$cf" ||
      missing="${missing} $(basename "$cf")"
  done
  if [ -n "$missing" ]; then
    echo "FAIL: calls install-desktop.sh but never COPY manifests —${missing}" >&2
    return 1
  fi
}

@test "apt-based Containerfiles guarantee systemd-cryptenroll is present" {
  # fisherman aborts before touching the disk without systemd-cryptenroll:
  #   fatal: missing required host tool: "systemd-cryptenroll" not found in
  #   PATH — install the "systemd" package on the host
  #
  # Which package ships it is NOT stable across releases, so asserting a
  # package name here is wrong. Measured against the archives:
  #   Debian trixie              -> systemd-cryptsetup
  #   Ubuntu noble    (gurnard)  -> systemd            (no systemd-cryptsetup)
  #   Ubuntu resolute (grouper)  -> systemd-cryptsetup (systemd dropped it)
  #
  # Containerfile.ubuntu serves BOTH Ubuntu releases, so naming either package
  # unconditionally breaks the other — hardcoding systemd-cryptsetup is what
  # made gurnard fail with "E: Unable to locate package systemd-cryptsetup"
  # (LUKS run 31061160416).
  #
  # The invariant that actually matters is that the binary exists in the built
  # image, and that the build says so rather than deferring the discovery to a
  # VM 40 minutes later. Assert the guard, not the package.
  local cf
  for cf in Containerfile.debian Containerfile.ubuntu; do
    local path="${REPO_ROOT}/${cf}" body
    # Strip comments: both the package names and the binary name appear in the
    # prose explaining this, so matching the raw file passes even when the
    # check is deleted. An earlier version of this test did exactly that.
    body="$(grep -v '^[[:space:]]*#' "$path")"
    grep -qE '(^|[[:space:]])cryptsetup([[:space:]]|\\|$)' <<<"$body" || {
      echo "FAIL: ${cf} does not install cryptsetup" >&2
      return 1
    }
    grep -qF 'command -v systemd-cryptenroll' <<<"$body" || {
      echo "FAIL: ${cf} never asserts systemd-cryptenroll is present" >&2
      return 1
    }
  done
}
