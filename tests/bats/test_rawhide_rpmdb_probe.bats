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
    # Real rpm leaves the completed rebuild dir behind when its rename
    # endgame fails; the salvage path picks that up.
    # NO_SALVAGE models the case where the rebuild failed and left no
    # completed product behind. It used to be expressed by leaving
    # RPM_DBPATH_OUT empty, which is precisely the input that made the probe
    # resolve %_dbpath to the working directory and delete it.
    if [[ "${REBUILD_RC:-0}" != 0 && -z "${NO_SALVAGE:-}" && -n "${RPM_DBPATH_OUT:-}" ]]; then
      mkdir -p "${RPM_DBPATH_OUT%/*}/rpmrebuilddb.42"
      echo rebuilt > "${RPM_DBPATH_OUT%/*}/rpmrebuilddb.42/rpmdb.sqlite"
    fi
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

  # Give every test a REAL dbpath under the scratch dir by default.
  #
  # Six of the eight tests here used to leave RPM_DBPATH_OUT unset, so the stub
  # printed an empty string, and the probe under test resolved it with
  # `readlink -f ""` -- which does not fail, it returns the CURRENT WORKING
  # DIRECTORY. The probe's copy-up then ran `cp -a` + `rm -rf` on bats's cwd,
  # i.e. the repository. That destroyed a checkout of this repo during a full
  # suite run: the disk was nearly full, the copy failed, and the delete was
  # not conditional on it. lib.sh is fixed to refuse a non-absolute dbpath, and
  # this default means the suite never steers it at a real directory again.
  RPM_DBPATH_OUT="${BATS_TEST_TMPDIR}/rpmdb"
  mkdir -p "$RPM_DBPATH_OUT"
  export RPM_DBPATH_OUT
}

# IS_FEDORA defaults to true here because every case below models a FEDORA
# image (Rawhide or pinned). It used to be unset, which meant these tests
# reached the probe the same way CentOS did in production — through
# detect_fedora_ver mapping an unexpanded %fedora to "rawhide" — rather than
# by being a Fedora at all. See tunaOS#1823; the non-Fedora case is now
# asserted explicitly below instead of being the accidental default.
run_probe() {
  PATH="${BIN}:$PATH" IS_FEDORA="${IS_FEDORA:-true}" NO_SALVAGE="${NO_SALVAGE:-}" run bash -c "
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

@test "off Fedora entirely, the probe is a no-op — CentOS is not Rawhide" {
  # The regression this guard exists for. On CentOS/RHEL/Alma `rpm -E %fedora`
  # prints the macro back unexpanded, detect_fedora_ver reports "rawhide", and
  # before the IS_FEDORA guard the Rawhide-only copy-up ran on a CentOS image
  # and then aborted the build on a lossy salvage (skipjack,
  # centos-bootc:stream10, run 32534198668).
  printf 'PRETTY_NAME="CentOS Stream 10"\n' > "$OS_RELEASE"
  IS_FEDORA=false RPM_E_OUT='%fedora' run_probe
  [ "$status" -eq 0 ]
  [[ "$output" != *"TUNAOS_RPMDB_PROBE"* ]]
  [ "$(wc -l < "$REBUILD_LOG")" -eq 0 ]
}

@test "detect_fedora_ver still reports rawhide there — the guard is what stops it" {
  # Pins the MECHANISM, not just the outcome: detect_fedora_ver is deliberately
  # left alone, because 10-base-packages.sh depends on that fallback inside an
  # `elif [[ $IS_FEDORA == true ]]` branch. If a later change "fixes" the
  # helper instead, this test says so.
  PATH="${BIN}:$PATH" run bash -c "
    set -euo pipefail
    ${FN_DETECT}
    RPM_E_OUT='%fedora' detect_fedora_ver
  "
  [ "$status" -eq 0 ]
  [[ "$output" == "rawhide" ]]
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
  # NO_SALVAGE=1: the rebuild fails AND leaves nothing to salvage. That used
  # to be modelled by an empty %_dbpath, which is the dangerous input — see
  # the guard tests at the end of this file.
  NO_SALVAGE=1 REBUILD_RC=1 run_probe
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

@test "a failed rebuild with a completed product is salvaged file-level" {
  # tunaOS#1823 round 4: a db corrupted at rest by an earlier stage needs
  # the rebuild's PRODUCT, and rpm builds it before the rename fails —
  # its own error text says to replace the files by hand. The probe does.
  mkdir -p "${BATS_TEST_TMPDIR}/rpmdb"
  echo corrupt > "${BATS_TEST_TMPDIR}/rpmdb/rpmdb.sqlite"
  RPM_DBPATH_OUT="${BATS_TEST_TMPDIR}/rpmdb" REBUILD_RC=1 run_probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_RPMDB_PROBE=rebuilt-salvaged"* ]]
  [ "$(cat "${BATS_TEST_TMPDIR}/rpmdb/rpmdb.sqlite")" = "rebuilt" ]
  [ ! -e "${BATS_TEST_TMPDIR}/rpmrebuilddb.42" ]
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

@test "an empty %_dbpath must never touch the working directory" {
  # The exact shape that deleted a checkout: `rpm --eval %_dbpath` yields
  # nothing, `readlink -f ""` returns $PWD, and the copy-up's rm -rf lands on
  # the working directory. Run from a scratch cwd and assert it survives.
  local victim="${BATS_TEST_TMPDIR}/victim"
  mkdir -p "$victim"
  echo precious > "${victim}/data.txt"

  cd "$victim"
  RPM_DBPATH_OUT="" run_probe
  cd "$BATS_TEST_TMPDIR"

  # The guard must refuse the empty path rather than resolve it.
  [[ "$output" == *"gave no absolute path"* ]]
  # ...and the directory the probe was standing in is still there.
  [ -f "${victim}/data.txt" ]
  [ "$(cat "${victim}/data.txt")" = "precious" ]
}

@test "a relative %_dbpath is refused too" {
  # readlink -f resolves a relative path against $PWD just as happily as it
  # resolves an empty one, so the guard tests for a leading slash, not just
  # for non-emptiness.
  local victim="${BATS_TEST_TMPDIR}/victim2"
  mkdir -p "$victim"
  echo precious > "${victim}/data.txt"

  cd "$victim"
  RPM_DBPATH_OUT="relative/rpmdb" run_probe
  cd "$BATS_TEST_TMPDIR"

  [[ "$output" == *"gave no absolute path"* ]]
  [ -f "${victim}/data.txt" ]
}
