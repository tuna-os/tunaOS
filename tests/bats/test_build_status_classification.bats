#!/usr/bin/env bats
# The README build matrix must not call an untested cell a failing one
# (tunaOS#1730).
#
# .github/scripts/update-build-status.sh used to sort every non-success
# promotion into one "Blocked or failing tags" column: a real `failure`, a
# `skipped` job, and `missing` (no Promote job existed at all) were rendered
# identically. On the 2026-08-14 sweep that mislabelled 14 flavors across
# sailfin/marlin/flounder/gurnard whose stage-2 group never ran, because the
# base manifest failed first (tunaOS#1729) — the front page asserted they were
# blocked or failing when nothing had tested them.
#
# This is the same conflation docs/MATRIX-STATUS.md exists to prevent:
# "absence of evidence read as evidence of absence". These tests drive the real
# script with stubbed `gh`/`yq`, so a regression that re-merges the buckets
# fails here rather than on the README.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/.github/scripts/update-build-status.sh"

setup() {
  BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$BIN"

  # yq: one variant, four flavors. The script asks for the flavor list, the
  # (id, emoji) pairs, and — since the composite count — the green-criteria
  # blocking set and the boots scope. The excludes cases must precede the
  # generic *flavors* one: their queries also contain the word "flavors".
  cat > "${BIN}/yq" <<'STUB'
#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in
    *excludes_flavor*) exit 0 ;;
    *enforcement*)     printf 'boots\nbuilds\n'; exit 0 ;;
    *flavors*)         printf 'green\nbroken\nskipped\nabsent\n'; exit 0 ;;
    *emoji*)           printf 'sailfin\t🦈\n'; exit 0 ;;
  esac
done
exit 0
STUB

  # gh: `run list` returns the run window, `api` returns Promote job results.
  # GH_RUNS / GH_JOBS let each test choose its own fixture.
  cat > "${BIN}/gh" <<'STUB'
#!/usr/bin/env bash
case "$1" in
  run) printf '%s' "${GH_RUNS}" ;;
  api) printf '%s' "${GH_JOBS}" ;;
esac
STUB

  chmod +x "${BIN}/yq" "${BIN}/gh"

  README="${BATS_TEST_TMPDIR}/README.md"
  printf '<!-- build-status:start -->\nstale\n<!-- build-status:end -->\n' > "$README"

  # One conclusive run by default.
  export GH_RUNS='[{"databaseId":1,"conclusion":"failure","createdAt":"2026-08-14T03:00:00Z","url":"https://example/1"}]'
  # green succeeded, broken failed, skipped was skipped, absent has no job.
  export GH_JOBS=$'sailfin / green / Promote\tsuccess\nsailfin / broken / Promote\tfailure\nsailfin / skipped / Promote\tskipped\n'
}

run_generator() {
  PATH="${BIN}:$PATH" run bash "$SCRIPT" "${BATS_TEST_TMPDIR}/config.yml" "$README"
}

@test "a job that ran and failed is reported as failing" {
  run_generator
  [ "$status" -eq 0 ]
  # Column 4 is Failing; `broken` is the only cell a job actually failed on.
  grep -qE '^\| 🦈 `sailfin` \|.*\| broken \|' "$README"
}

@test "skipped and missing cells are reported as not reached, not failing" {
  run_generator
  [ "$status" -eq 0 ]
  local row
  row=$(grep '`sailfin`' "$README")
  # Both land in the final column together. The join is comma-only, matching
  # the format the table already used (`base,base-hwe,...`).
  [[ "$row" == *"| skipped,absent |"* ]]
  # ...and the failing column holds only the cell a job actually failed on.
  [[ "$row" == *"| broken | skipped,absent |"* ]]
}

@test "the green count only counts successful promotions" {
  run_generator
  grep -q '\*\*1/4\*\*' "$README"
}

@test "the summary separates failing from never-reached" {
  run_generator
  grep -q '1 failing' "$README"
  grep -q '2 never reached' "$README"
}

@test "a cancelled run is skipped in favour of the newest conclusive one" {
  # docs/MATRIX-STATUS.md: "a superseded run is not a broken build".
  export GH_RUNS='[{"databaseId":9,"conclusion":"cancelled","createdAt":"2026-08-15T03:00:00Z","url":"https://example/9"},{"databaseId":1,"conclusion":"success","createdAt":"2026-08-14T03:00:00Z","url":"https://example/1"}]'
  run_generator
  [ "$status" -eq 0 ]
  # The conclusive run is the one linked and iconified, not the cancellation.
  grep -q 'example/1' "$README"
  grep -q '✅ 2026-08-14' "$README"
  ! grep -q 'example/9' "$README"
}

@test "a cancelled run is labelled as cancelled when it is all there is" {
  export GH_RUNS='[{"databaseId":9,"conclusion":"cancelled","createdAt":"2026-08-15T03:00:00Z","url":"https://example/9"}]'
  run_generator
  [ "$status" -eq 0 ]
  # Not ❌: nothing about this run says the variant is broken.
  grep -q '🚫 2026-08-15' "$README"
  ! grep -q '❌ 2026-08-15' "$README"
}

@test "a variant with no completed run at all counts as never reached" {
  export GH_RUNS='[]'
  run_generator
  [ "$status" -eq 0 ]
  grep -q 'no completed run' "$README"
  grep -q '4 never reached' "$README"
}

# --- composite green when the blocking set outgrows this script -------------
#
# `desktop` and `no_silent_omissions` graduated to blocking on 2026-08-19.
# This script can only read `builds` and `boots` off Actions job names, and
# its response was to exit 1 — which froze the README block for two weeks
# rather than publishing a number that had stopped meaning what it said.
# It now takes gen-matrix-status.py's count, which scores every axis.

blocking_stub() {
  cat > "${BIN}/yq" <<'STUB'
#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in
    *excludes_flavor*) exit 0 ;;
    *enforcement*)     printf 'boots\nbuilds\ndesktop\nno_silent_omissions\n'; exit 0 ;;
    *flavors*)         printf 'green\nbroken\nskipped\nabsent\n'; exit 0 ;;
    *emoji*)           printf 'sailfin\t🦈\n'; exit 0 ;;
  esac
done
exit 0
STUB
  chmod +x "${BIN}/yq"
}

@test "an unscorable blocking set takes its composite from MATRIX-STATUS.md" {
  blocking_stub
  export MATRIX_STATUS_DOC="${BATS_TEST_TMPDIR}/MATRIX-STATUS.md"
  printf '## Composite green\n\n**68 of 145** published cells are composite-green.\n' \
    > "$MATRIX_STATUS_DOC"
  run_generator
  [ "$status" -eq 0 ]
  # The sourced pair, over its own denominator — not this table's four cells.
  grep -q 'composite green 68/145' "$README"
  grep -q 'published cells, per \[docs/MATRIX-STATUS.md\]' "$README"
}

@test "the footer names every blocking criterion, not a stale pair" {
  blocking_stub
  export MATRIX_STATUS_DOC="${BATS_TEST_TMPDIR}/MATRIX-STATUS.md"
  printf '**68 of 145** published cells are composite-green.\n' > "$MATRIX_STATUS_DOC"
  run_generator
  [ "$status" -eq 0 ]
  grep -q 'blocking today on `boots`, `builds`, `desktop`, `no_silent_omissions`' "$README"
}

@test "a MATRIX-STATUS.md with no composite line is an error, not a guess" {
  blocking_stub
  export MATRIX_STATUS_DOC="${BATS_TEST_TMPDIR}/MATRIX-STATUS.md"
  printf 'no composite sentence here\n' > "$MATRIX_STATUS_DOC"
  run_generator
  [ "$status" -eq 1 ]
  [[ "$output" == *"carries no"* ]]
  # The README keeps whatever it had rather than gaining a wrong number.
  grep -q 'stale' "$README"
}

@test "a scorable blocking set still scores itself, with no document to read" {
  # boots+builds is what this script can measure; it must not start depending
  # on a generated document for the case it has always handled.
  export MATRIX_STATUS_DOC="${BATS_TEST_TMPDIR}/absent.md"
  run_generator
  [ "$status" -eq 0 ]
  # 0, not 1: `green` promoted but no Gate asserted it, and a Gate that never
  # ran is not a pass (skipped_is_not_green).
  grep -q 'composite green 0/4' "$README"
  grep -q 'counts this table' "$README"
}
