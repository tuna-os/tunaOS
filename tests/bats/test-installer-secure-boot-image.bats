#!/usr/bin/env bats
# The Secure Boot layer for BuildStream sibling images (tunaOS#4955).
#
# The static tests need no network and no container engine. The last test
# signs a real image with a throwaway key and runs the key-free check; it
# runs only when SB_TEST_IMAGE names an image in the local container storage:
#   SB_TEST_IMAGE=ghcr.io/tuna-os/tromso:latest bats tests/bats/test-installer-secure-boot-image.bats
# SB_TEST_REJECT_CERT can name a certificate that must not verify a boot file.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SB="${REPO_ROOT}/installer-medium/secure-boot"
IMG="${SB}/image"

pin() {
  python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["shim"]["x64"][sys.argv[2]])' "${IMG}/shim.toml" "$1"
}

@test "the image scripts pass shellcheck" {
  command -v shellcheck >/dev/null || skip "shellcheck not installed"
  run shellcheck "${IMG}/sign-image.sh" "${IMG}/verify-image.sh"
  [ "$status" -eq 0 ]
}

@test "the shim pin is a Fedora release RPM with a sha256, a licence and a source" {
  [[ "$(pin url)" =~ ^https://kojipkgs\.fedoraproject\.org/packages/shim/[0-9.]+/[0-9]+/x86_64/shim-x64-[0-9.-]+\.x86_64\.rpm$ ]]
  [[ "$(pin sha256)" =~ ^[0-9a-f]{64}$ ]]
  [ "$(pin license)" = "BSD-3-Clause" ]
  [ "$(pin upstream)" = "https://github.com/rhboot/shim" ]
  [[ "$(pin url)" == *"shim-x64-$(pin version)"* ]]
  [[ "$(pin shim)" == usr/lib/efi/shim/"$(pin version)"/EFI/fedora/shimx64.efi ]]
  [[ "$(pin mok_manager)" == usr/lib/efi/shim/"$(pin version)"/EFI/fedora/mmx64.efi ]]
}

@test "sign-image refuses a shell trace, a missing argument and a second architecture" {
  run bash -x "${IMG}/sign-image.sh" a b
  [ "$status" -ne 0 ]
  [[ "$output" == *"refuse to run under set -x"* ]]
  run "${IMG}/sign-image.sh" only-one
  [ "$status" -ne 0 ]
  SB_ARCH=aa64 run "${IMG}/sign-image.sh" a b
  [ "$status" -ne 0 ]
  [[ "$output" == *"only x64 has a shim pin"* ]]
}

@test "sign-image never reads the key and gives no secret to a container" {
  # Only ci-sign.sh reads the secrets. A non-comment line that names one
  # would put the key in a second place.
  run grep -nE '^[^#]*TUNAOS_SB_KEY' "${IMG}/sign-image.sh" "${IMG}/verify-image.sh"
  [ "$status" -eq 1 ]
  run grep -nE 'podman.*(--env|-e |--secret)|"\$\{PODMAN\}" run' "${IMG}/sign-image.sh" "${IMG}/verify-image.sh"
  [ "$status" -eq 1 ]
}

@test "the layer holds each file of the image contract in SECURE-BOOT.md" {
  doc="${REPO_ROOT}/installer-medium/docs/SECURE-BOOT.md"
  for path in shimx64.efi mmx64.efi tunaos-secure-boot.cer 'keys/auto' mode systemd-bootx64.efi.signed /usr/bin/tuna-secure-boot; do
    grep -qF "${path}" "${doc}"
  done
  for token in 'shim${ARCH}.efi' 'mm${ARCH}.efi' tunaos-secure-boot.cer keys/auto "printf 'tunaos-key" '${LOADER}.signed' usr/bin/tuna-secure-boot; do
    grep -qF -- "${token}" "${IMG}/sign-image.sh"
  done
}

@test "verify-image needs an image and a readable certificate for --reject-cert" {
  run "${IMG}/verify-image.sh"
  [ "$status" -ne 0 ]
  run "${IMG}/verify-image.sh" some-image --reject-cert /nonexistent.pem
  [ "$status" -eq 2 ]
}

@test "a real image signed with a throwaway key keeps the contract (opt-in)" {
  [ -n "${SB_TEST_IMAGE:-}" ] || skip "set SB_TEST_IMAGE to an image in the local container storage"
  for tool in podman sbsign sbverify sbattach sbvarsign openssl; do
    command -v "$tool" >/dev/null || skip "needs $tool"
  done
  T="$(mktemp -d)"
  openssl req -new -x509 -newkey rsa:2048 -nodes -keyout "${T}/test.key" -out "${T}/test.crt" \
    -days 2 -subj "/CN=THROWAWAY sign-image test" -addext "basicConstraints=critical,CA:FALSE" \
    -addext "extendedKeyUsage=codeSigning" 2>/dev/null
  out="localhost/sb-test-signed:$$"
  # The unsigned image must fail the check.
  SB_CERT="${T}/test.crt" run "${IMG}/verify-image.sh" "${SB_TEST_IMAGE}"
  [ "$status" -ne 0 ]
  TUNAOS_SB_KEY="$(cat "${T}/test.key")" TUNAOS_SB_CERT="$(cat "${T}/test.crt")" SB_CERT="${T}/test.crt" \
    run "${IMG}/sign-image.sh" "${SB_TEST_IMAGE}" "${out}"
  echo "$output"
  [ "$status" -eq 0 ]
  reject=()
  [ -z "${SB_TEST_REJECT_CERT:-}" ] || reject=(--reject-cert "${SB_TEST_REJECT_CERT}")
  SB_CERT="${T}/test.crt" run "${IMG}/verify-image.sh" "${out}" "${reject[@]}"
  echo "$output"
  [ "$status" -eq 0 ]
  # The throwaway signature is not the tunaOS signature.
  run "${IMG}/verify-image.sh" "${out}"
  [ "$status" -ne 0 ]
  [[ "$output" == *"does not verify against the tunaOS certificate"* ]]
  podman rmi "${out}" >/dev/null
  rm -rf "${T}"
}
