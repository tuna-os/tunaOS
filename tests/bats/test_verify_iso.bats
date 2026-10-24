#!/usr/bin/env bats
#
# Exercise scripts/verify-iso.sh itself with a fake limactl and sleep. The
# verifier still builds its real Lima config, parses real JSON status output,
# reads the real serial-log path, and runs its real cleanup trap; only the
# long-running VM operations are stubbed.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/scripts/verify-iso.sh"
  STUB_BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "${STUB_BIN}" "${BATS_TEST_TMPDIR}/home"
  HOME="${BATS_TEST_TMPDIR}/home"
  export HOME

  cat >"${STUB_BIN}/limactl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  list)
    case "${2:-}" in
      -q)
        if [[ -n "${LIMA_EXISTING:-}" || -f "${LIMA_STARTED_MARKER}" ]]; then
          printf '%s\n' "${LIMA_EXISTING:-$LIMA_TEST_NAME}"
        fi
        ;;
      --json)
        printf '{"name":"%s","status":"%s"}\n' \
          "${LIMA_TEST_NAME}" "${LIMA_STATUS:-Running}"
        ;;
    esac
    ;;
  delete)
    printf 'delete %s\n' "${2:-}" >>"${LIMA_EVENTS}"
    ;;
  start)
    name=""
    config=""
    for arg in "$@"; do
      case "$arg" in
        --name=*) name="${arg#--name=}" ;;
        *.yaml) config="$arg" ;;
      esac
    done
    printf 'start %s\n' "$name" >>"${LIMA_EVENTS}"
    : >"${LIMA_STARTED_MARKER}"
    cp "$config" "${LIMA_CONFIG_CAPTURE}"
    mkdir -p "${HOME}/.lima/${name}"
    printf '%s\n' "${LIMA_SERIAL:-GRUB version 2.12}" \
      >"${HOME}/.lima/${name}/serial.log"
    ;;
  *)
    printf 'unexpected limactl call: %s\n' "$*" >&2
    exit 2
    ;;
esac
EOF
  chmod +x "${STUB_BIN}/limactl"

  cat >"${STUB_BIN}/sleep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "${STUB_BIN}/sleep"

  cat >"${STUB_BIN}/uname" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "-m" ]]; then
  printf '%s\n' "${UNAME_MACHINE:-x86_64}"
else
  exec /usr/bin/uname "$@"
fi
EOF
  chmod +x "${STUB_BIN}/uname"

  ISO_FILE="${BATS_TEST_TMPDIR}/Yellowfin-GNOME-10-x86_64.iso"
  : >"${ISO_FILE}"
  LIMA_EVENTS="${BATS_TEST_TMPDIR}/limactl.events"
  LIMA_STARTED_MARKER="${BATS_TEST_TMPDIR}/limactl.started"
  LIMA_CONFIG_CAPTURE="${BATS_TEST_TMPDIR}/lima-config.yaml"
  export ISO_FILE LIMA_EVENTS LIMA_STARTED_MARKER LIMA_CONFIG_CAPTURE
  LIMA_TEST_NAME="verify-iso-yellowfin-gnome-10-x86-64"
  export LIMA_TEST_NAME
}

@test "requires exactly one argument" {
  run env PATH="/usr/bin:/bin" bash "${SCRIPT}"

  [ "$status" -eq 1 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "rejects missing ISO before checking limactl" {
  run env PATH="${STUB_BIN}:/usr/bin:/bin" bash "${SCRIPT}" \
    "${BATS_TEST_TMPDIR}/missing.iso"

  [ "$status" -eq 1 ]
  [[ "$output" == *"ISO file not found"* ]]
}

@test "rejects host without limactl" {
  run env PATH="/usr/bin:/bin" bash "${SCRIPT}" "${ISO_FILE}"

  [ "$status" -eq 1 ]
  [[ "$output" == *"limactl is not installed"* ]]
}

@test "runs real verifier and emits x86 Lima config" {
  run env PATH="${STUB_BIN}:/usr/bin:/bin" bash "${SCRIPT}" "${ISO_FILE}"

  [ "$status" -eq 0 ]
  [[ "$output" == *"Lima instance: ${LIMA_TEST_NAME}"* ]]
  [[ "$output" == *"ISO Verification PASSED"* ]]
  grep -Fq "location: \"${ISO_FILE}\"" "${LIMA_CONFIG_CAPTURE}"
  grep -Fq "arch: x86_64" "${LIMA_CONFIG_CAPTURE}"
  grep -Fq "plain: true" "${LIMA_CONFIG_CAPTURE}"
  grep -Fq "vmType: qemu" "${LIMA_CONFIG_CAPTURE}"
  grep -Fq "start ${LIMA_TEST_NAME}" "${LIMA_EVENTS}"
  grep -Fq "delete ${LIMA_TEST_NAME}" "${LIMA_EVENTS}"
}

@test "maps arm64 host to aarch64 Lima architecture" {
  run env PATH="${STUB_BIN}:/usr/bin:/bin" UNAME_MACHINE=arm64 \
    bash "${SCRIPT}" "${ISO_FILE}"

  [ "$status" -eq 0 ]
  grep -Fq "arch: aarch64" "${LIMA_CONFIG_CAPTURE}"
}

@test "deletes pre-existing VM before starting replacement" {
  run env PATH="${STUB_BIN}:/usr/bin:/bin" LIMA_EXISTING="${LIMA_TEST_NAME}" \
    bash "${SCRIPT}" "${ISO_FILE}"

  [ "$status" -eq 0 ]
  [ "$(sed -n '1p' "${LIMA_EVENTS}")" = "delete ${LIMA_TEST_NAME}" ]
  [ "$(sed -n '2p' "${LIMA_EVENTS}")" = "start ${LIMA_TEST_NAME}" ]
}

@test "fails when Lima reports missing VM" {
  run env PATH="${STUB_BIN}:/usr/bin:/bin" LIMA_STATUS=missing \
    bash "${SCRIPT}" "${ISO_FILE}"

  [ "$status" -eq 1 ]
  [[ "$output" == *"Lima VM is gone or broken"* ]]
}

@test "fails when Lima reports broken VM" {
  run env PATH="${STUB_BIN}:/usr/bin:/bin" LIMA_STATUS=Broken \
    bash "${SCRIPT}" "${ISO_FILE}"

  [ "$status" -eq 1 ]
  [[ "$output" == *"Lima VM is gone or broken"* ]]
}

@test "fails on fatal serial-log boot error" {
  run env PATH="${STUB_BIN}:/usr/bin:/bin" \
    LIMA_SERIAL="Kernel panic - not syncing: Attempted to kill init!" \
    bash "${SCRIPT}" "${ISO_FILE}"

  [ "$status" -eq 1 ]
  [[ "$output" == *"Fatal boot error detected"* ]]
}

@test "fails when serial log has no boot indicator" {
  run env PATH="${STUB_BIN}:/usr/bin:/bin" LIMA_SERIAL="random noise" \
    bash "${SCRIPT}" "${ISO_FILE}"

  [ "$status" -eq 1 ]
  [[ "$output" == *"no boot indicators in serial log"* ]]
}
