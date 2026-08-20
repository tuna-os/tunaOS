#!/usr/bin/env bats
# rawhide_rpmdb_probe() — tunaOS#1823.
#
# Stage-2 on a fresh Rawhide base fails with "database disk image is
# malformed" (sqlite error 11) on every RPM install once the transaction is
# desktop-sized; small overlays pass; both arches; survives all retries. The
# probe rebuilds the rpmdb inherited from the base BEFORE stage-2's first rpm
# write, and its marker discriminates the three hypotheses in the issue.
#
# Runs the REAL functions extracted verbatim from build_scripts/lib.sh (the
# extract-and-run technique of test_install_rawhide_tolerant.bats) against
# mocked rpm.

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
LIB="${REPO_ROOT}/build_scripts/lib.sh"

setup() {
  BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$BIN"

  FN_PROBE="$(awk '/^rawhide_rpmdb_probe\(\)/,/^}/' "$LIB")"
  FN_DETECT="$(awk '/^detect_fedora_ver\(\)/,/^}/' "$LIB")"
  [[ -n "$FN_PROBE" ]]
  [[ -n "$FN_DETECT" ]]

  # Mock rpm: `-E %fedora` prints RPM_E_OUT; `--rebuilddb` exits
  # REBUILD_RC and records that it was invoked.
  cat > "${BIN}/rpm" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  -E) printf '%s\n' "${RPM_E_OUT:-45}" ;;
  --eval) printf '%s\n' "${RPM_DBPATH_OUT:-}" ;;
  --rebuilddb)
    echo invoked >> "${REBUILD_LOG}"
    exit "${REBUILD_RC:-0}"
    ;;
esac
STUB
  chmod +x "${BIN}/rpm"

  REBUILD_LOG="${BATS_TEST_TMPDIR}/rebuilds"
  : > "$REBUILD_LOG"
  export REBUILD_LOG

  OS_RELEASE="${BATS_TEST_TMPDIR}/os-release"
  printf 'PRETTY_NAME="Fedora Linux Rawhide (Prerelease)"\n' > "$OS_RELEASE"
  export OS_RELEASE
}

run_probe() {
  PATH="${BIN}:$PATH" run bash -c "
    set -euo pipefail
    ${FN_DETECT}
    ${FN_PROBE}
    rawhide_rpmdb_probe
  "
}

@test "on rawhide, the inherited rpmdb is rebuilt and the marker says so" {
  run_probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_RPMDB_PROBE=rebuilt"* ]]
  [ "$(wc -l < "$REBUILD_LOG")" -eq 1 ]
}

@test "off rawhide, the probe is a no-op — pinned Fedora never pays for it" {
  printf 'PRETTY_NAME="Fedora Linux 44 (Container Image)"\n' > "$OS_RELEASE"
  RPM_E_OUT=44 run_probe
  [ "$status" -eq 0 ]
  [[ "$output" != *"TUNAOS_RPMDB_PROBE"* ]]
  [ "$(wc -l < "$REBUILD_LOG")" -eq 0 ]
}

@test "a failed rebuild warns but does not fail the build" {
  # Re-diagnosed on the nvidia surface (run 32339591457): the rebuild's
  # replace step ends in directory renames that fail under the overlay
  # even against an upper-native dir — it is not evidence of a malformed
  # source db. The round-trip is the fix; the transaction that follows is
  # the real verdict, so a rebuild failure only warns.
  REBUILD_RC=1 run_probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_RPMDB_PROBE=rebuild-failed-nonfatal"* ]]
  [[ "$output" == *"real verdict"* ]]
}

@test "the resolved rpmdb dir is round-tripped into the upper layer first" {
  # The proven #1823 fix (albacore base-nvidia went red→green on it):
  # recreate the resolved db directory natively in the upper layer before
  # the first rpm write. The sentinel proves the contents survive the
  # cp -a → rm -rf → mv round trip; no .tbox-copyup residue remains.
  mkdir -p "${BATS_TEST_TMPDIR}/rpmdb"
  echo sentinel > "${BATS_TEST_TMPDIR}/rpmdb/rpmdb.sqlite"
  RPM_DBPATH_OUT="${BATS_TEST_TMPDIR}/rpmdb" run_probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"recreating it in the upper layer"* ]]
  [ "$(cat "${BATS_TEST_TMPDIR}/rpmdb/rpmdb.sqlite")" = "sentinel" ]
  [ ! -e "${BATS_TEST_TMPDIR}/rpmdb.tbox-copyup" ]
}

@test "stage-2 calls the probe before its first rpm write" {
  # The probe must precede every dnf/rpm invocation on the dnf path of
  # 20-packages.sh, or it measures nothing.
  script="${REPO_ROOT}/build_scripts/20-packages.sh"
  probe_line="$(grep -n '^rawhide_rpmdb_probe' "$script" | head -1 | cut -d: -f1)"
  [ -n "$probe_line" ]
  first_write="$(grep -nE 'dnf_retry|dnf -y|rpm -[iU]' "$script" | head -1 | cut -d: -f1)"
  [ -n "$first_write" ]
  [ "$probe_line" -lt "$first_write" ]
}
