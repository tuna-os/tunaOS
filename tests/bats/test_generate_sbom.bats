#!/usr/bin/env bats
# scripts/generate-sbom.sh — tunaOS#1987.
#
# This logic used to live inline in the `Generate SBOM` step of
# reusable-build-image.yml, where its own comments record four incidents
# (#956, #1567, #1572, the 2026-08-16 guppy nightly) caused by its edge
# cases — and where nothing could exercise it short of a nightly build.
#
# These tests run the REAL script against mocked free/systemd-run/sudo/syft,
# the same technique test_install_rawhide_tolerant.bats uses. They pin the
# three behaviours that the incidents were about: what the cgroup cap is
# computed to be, that the floor wins on a small runner, and that losing
# systemd-run degrades loudly rather than silently.
#
# The workflow step still inlines the same body, because pointing it at the
# file needs the `workflows` permission the agent App does not hold. The
# last test here is the drift guard that keeps the two copies byte-identical
# until a maintainer makes that swap — without it these tests would be
# testing a copy CI does not run.

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
SCRIPT="${REPO_ROOT}/scripts/generate-sbom.sh"

setup() {
  BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$BIN"
  PATH="${BIN}:${PATH}"

  cd "$BATS_TEST_TMPDIR"

  export IMAGE_REGISTRY="ghcr.io/tuna-os"
  export IMAGE_NAME="bonito"
  export DEFAULT_TAG="latest"
  export SAFE_PLATFORM="linux_amd64"
  export SYFT_CMD="syft"
  export SYFT_MEMORY_RESERVE_MIB="5120"
  export SYFT_MEMORY_FLOOR_MIB="2048"

  OUT="sbom-${IMAGE_NAME}-${DEFAULT_TAG}-${SAFE_PLATFORM}.spdx.json"

  # `free -m`: report MEM_TOTAL_MIB total / MEM_AVAIL_MIB available in the
  # column positions the script's awk reads ($2 and $7).
  cat >"${BIN}/free" <<'EOF'
#!/usr/bin/env bash
echo "               total        used        free      shared  buff/cache   available"
echo "Mem:    ${MEM_TOTAL_MIB}      1000        1000           0        1000   ${MEM_AVAIL_MIB}"
EOF

  # syft stand-in: writes a minimal but valid SPDX document to the -o target,
  # and records the argv it was handed so tests can assert the invocation.
  cat >"${BIN}/syft" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >>"${SYFT_ARGV_LOG}"
for arg in "$@"; do
  case "$arg" in
    spdx-json=*) out="${arg#spdx-json=}" ;;
  esac
done
if [ "${SYFT_EMIT_BAD_SBOM:-0}" = "1" ]; then
  printf '{"spdxVersion":"NOPE","packages":[]}\n' >"$out"
else
  printf '{"spdxVersion":"SPDX-2.3","packages":[{"name":"bash"}]}\n' >"$out"
fi
exit "${SYFT_RC:-0}"
EOF

  # systemd-run stand-in: log the cap it was asked for, then exec whatever
  # follows the `--` separator so the wrapped syft still runs.
  cat >"${BIN}/systemd-run" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >>"${SYSTEMD_RUN_ARGV_LOG}"
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--" ]; then shift; break; fi
  shift
done
exec "$@"
EOF

  # sudo stand-in: `sudo -n true` is the passwordless probe; anything else is
  # run as-is.
  cat >"${BIN}/sudo" <<'EOF'
#!/usr/bin/env bash
if [ "${SUDO_AVAILABLE:-1}" != "1" ]; then exit 1; fi
if [ "$1" = "-n" ]; then shift; fi
exec "$@"
EOF

  chmod +x "${BIN}/free" "${BIN}/syft" "${BIN}/systemd-run" "${BIN}/sudo"

  export SYFT_ARGV_LOG="${BATS_TEST_TMPDIR}/syft-argv.log"
  export SYSTEMD_RUN_ARGV_LOG="${BATS_TEST_TMPDIR}/systemd-run-argv.log"
  : >"$SYFT_ARGV_LOG"
  : >"$SYSTEMD_RUN_ARGV_LOG"

  export MEM_TOTAL_MIB=16384
  export MEM_AVAIL_MIB=14000
}

@test "cap is runner total minus the reserve on a normally-sized runner" {
  export MEM_TOTAL_MIB=16384   # 16384 - 5120 = 11264, well above the floor

  run "$SCRIPT"
  [ "$status" -eq 0 ]

  [[ "$output" == *"syft cgroup cap (MiB): 11264"* ]]
  grep -q -- "MemoryMax=11264M" "$SYSTEMD_RUN_ARGV_LOG"
}

@test "cap clamps to the floor when the reserve would eat the whole runner" {
  export MEM_TOTAL_MIB=6144    # 6144 - 5120 = 1024, below the 2048 floor

  run "$SCRIPT"
  [ "$status" -eq 0 ]

  [[ "$output" == *"syft cgroup cap (MiB): 2048"* ]]
  grep -q -- "MemoryMax=2048M" "$SYSTEMD_RUN_ARGV_LOG"
  ! grep -q -- "MemoryMax=1024M" "$SYSTEMD_RUN_ARGV_LOG"
}

@test "swap is disabled alongside the memory cap" {
  run "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q -- "MemorySwapMax=0" "$SYSTEMD_RUN_ARGV_LOG"
}

@test "losing systemd-run warns loudly and still runs syft" {
  rm -f "${BIN}/systemd-run"

  run "$SCRIPT"
  [ "$status" -eq 0 ]

  [[ "$output" == *"::warning::systemd-run unavailable"* ]]
  [[ "$output" == *"NOT memory-bounded"* ]]
  grep -q -- "--scope squashed" "$SYFT_ARGV_LOG" || grep -q -- "squashed" "$SYFT_ARGV_LOG"
  [ -s "$OUT" ]
}

@test "losing passwordless sudo takes the same unbounded fallback" {
  export SUDO_AVAILABLE=0

  run "$SCRIPT"
  [ "$status" -eq 0 ]

  [[ "$output" == *"::warning::systemd-run unavailable"* ]]
  [ ! -s "$SYSTEMD_RUN_ARGV_LOG" ]
  [ -s "$OUT" ]
}

@test "syft scans the squashed image ref the caller asked for" {
  run "$SCRIPT"
  [ "$status" -eq 0 ]

  grep -qx "ghcr.io/tuna-os/bonito:latest-linux_amd64" "$SYFT_ARGV_LOG"
  grep -qx -- "--scope" "$SYFT_ARGV_LOG"
  grep -qx "squashed" "$SYFT_ARGV_LOG"
  grep -qx "spdx-json=${OUT}" "$SYFT_ARGV_LOG"
}

@test "a scan that produces a non-SPDX document is rejected" {
  export SYFT_EMIT_BAD_SBOM=1

  run "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "a failing syft fails the script" {
  export SYFT_RC=1

  run "$SCRIPT"
  [ "$status" -ne 0 ]
}

@test "the workflow's inline copy has not drifted from the script" {
  wf="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"
  [ -f "$wf" ]

  # Everything from the first `set -euo pipefail` down is the shared body;
  # the lines above it are this file's own header.
  script_body="${BATS_TEST_TMPDIR}/from-script"
  sed -n '/^set -euo pipefail$/,$p' "$SCRIPT" >"$script_body"
  [ -s "$script_body" ]

  # The inline copy: the `run: |` block of the step whose id is `sbom`,
  # dedented by the 10 spaces YAML block scalars carry.
  inline_body="${BATS_TEST_TMPDIR}/from-workflow"
  awk '
    /^        id: sbom$/            { in_step = 1; next }
    in_step && /^        run: \|$/  { in_run = 1; in_step = 0; next }
    in_run {
      if ($0 ~ /^[[:space:]]*$/) { print ""; next }
      match($0, /^ */)
      if (RLENGTH <= 8) { exit }
      print substr($0, 11)
    }
  ' "$wf" >"$inline_body"
  [ -s "$inline_body" ]

  # Trailing blank lines are an artifact of where the YAML block ends.
  diff -u <(sed -e :a -e '/^\n*$/{$d;N;};/\n$/ba' "$script_body") \
          <(sed -e :a -e '/^\n*$/{$d;N;};/\n$/ba' "$inline_body")
}
