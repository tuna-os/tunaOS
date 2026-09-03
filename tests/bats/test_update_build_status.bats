#!/usr/bin/env bats
# Unit tests for .github/scripts/update-build-status.sh (tunaOS#1799).
#
# This is the script that regenerates the README build-status matrix from
# build-config.yml and the latest completed main-branch run of each variant
# workflow. It shelled out to `gh`/`yq` with zero test coverage before this
# file. tests/bats/test_build_status_classification.bats already exercises
# the failing-vs-not-reached conflation (tunaOS#1730); this file rounds out
# the issue's scope list: the fourth "unknown" cell state, render
# determinism, error handling on bad/missing input, and flag/arg defaults.
#
# Every test drives the real script (`gh`/`yq` are stubbed on PATH); no
# GitHub API calls are made.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/.github/scripts/update-build-status.sh"

setup() {
  BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$BIN"

  # yq: one variant ("sailfin"), four flavors covering each cell outcome.
  # The excludes cases must precede the generic *flavors* one: their queries
  # also contain the word "flavors".
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

  # gh: `run list` returns the run window, `api` returns Promote job
  # conclusions. GH_RUNS / GH_JOBS let each test pick its own fixture; GH_LOG
  # records every invocation so flag/default tests can assert on it.
  cat > "${BIN}/gh" <<'STUB'
#!/usr/bin/env bash
echo "gh $*" >> "${GH_LOG:-/dev/null}"
case "$1" in
  run) printf '%s' "${GH_RUNS}" ;;
  api) printf '%s' "${GH_JOBS}" ;;
esac
STUB

  chmod +x "${BIN}/yq" "${BIN}/gh"
  export PATH="${BIN}:${PATH}"
  export GH_LOG="${BATS_TEST_TMPDIR}/gh.log"

  CONFIG="${BATS_TEST_TMPDIR}/config.yml"
  README="${BATS_TEST_TMPDIR}/README.md"
  echo 'variants: []' > "$CONFIG"
  printf '<!-- build-status:start -->\nstale\n<!-- build-status:end -->\n' > "$README"

  # One conclusive run, one green/one failing/two never-reached cell, by
  # default.
  export GH_RUNS='[{"databaseId":1,"conclusion":"success","createdAt":"2026-08-14T03:00:00Z","url":"https://example/1"}]'
  export GH_JOBS=$'sailfin / green / Promote\tsuccess\nsailfin / broken / Promote\tfailure\nsailfin / skipped / Promote\tskipped\n'
}

run_generator() {
  run bash "$SCRIPT" "$@"
}

# ── cell classification: green / red / unbuilt / unknown ────────────────────

@test "classification: a promoted flavor is a green cell" {
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]
  grep -q '\*\*1/4\*\*' "$README"
}

@test "classification: a flavor whose Promote job failed is a red/failing cell" {
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]
  local row
  row=$(grep '`sailfin`' "$README")
  [[ "$row" == *"| broken |"* ]]
}

@test "classification: skipped or absent Promote jobs are unbuilt/not-reached cells, never failing" {
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]
  local row
  row=$(grep '`sailfin`' "$README")
  [[ "$row" == *"| broken | skipped,absent |"* ]]
}

@test "classification: a run conclusion outside success/failure/cancelled renders as the unknown icon" {
  # e.g. "neutral", "action_required", "startup_failure" -- anything gh can
  # report that this script has no dedicated bucket for.
  export GH_RUNS='[{"databaseId":1,"conclusion":"neutral","createdAt":"2026-08-14T03:00:00Z","url":"https://example/1"}]'
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]
  grep -q '⬜ 2026-08-14' "$README"
  ! grep -q '✅ 2026-08-14\|❌ 2026-08-14\|🚫 2026-08-14' "$README"
}

@test "classification: no completed run at all is reported distinctly, not as an unknown run" {
  export GH_RUNS='[]'
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]
  grep -q 'no completed run' "$README"
  grep -q '| — | all |' "$README"
}

# ── table render determinism ─────────────────────────────────────────────────

@test "determinism: the same fixture renders a byte-identical table on repeat runs" {
  local readme_a="${BATS_TEST_TMPDIR}/README_A.md"
  local readme_b="${BATS_TEST_TMPDIR}/README_B.md"
  printf '<!-- build-status:start -->\nstale\n<!-- build-status:end -->\n' > "$readme_a"
  printf '<!-- build-status:start -->\nstale\n<!-- build-status:end -->\n' > "$readme_b"

  run bash "$SCRIPT" "$CONFIG" "$readme_a"
  [ "$status" -eq 0 ]
  run bash "$SCRIPT" "$CONFIG" "$readme_b"
  [ "$status" -eq 0 ]

  diff "$readme_a" "$readme_b"
}

@test "determinism: re-running against an already-refreshed README is a no-op" {
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]
  cp "$README" "${BATS_TEST_TMPDIR}/README_once.md"

  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]

  diff "${BATS_TEST_TMPDIR}/README_once.md" "$README"
}

# ── error handling ────────────────────────────────────────────────────────────

@test "error handling: a missing status input (README) fails loudly instead of silently succeeding" {
  run_generator "$CONFIG" "${BATS_TEST_TMPDIR}/does-not-exist.md"
  [ "$status" -ne 0 ]
}

@test "error handling: a config with no configured cells exits non-zero instead of publishing a bogus percentage" {
  # An empty variant list means total_cells stays 0; the script must not
  # silently divide by it and claim some percentage built.
  cat > "${BIN}/yq" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
  chmod +x "${BIN}/yq"
  run_generator "$CONFIG" "$README"
  [ "$status" -ne 0 ]
  # The README is left untouched rather than gaining a corrupted table.
  grep -q 'stale' "$README"
}

@test "error handling: an unparseable run-status payload degrades to 'no completed run' rather than crashing" {
  # gh occasionally hands back something jq can't parse (rate-limit HTML,
  # truncated output). The script must still finish and produce a report.
  export GH_RUNS='not json at all'
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]
  grep -q 'no completed run' "$README"
}

@test "error handling: an unscorable blocking set with no MATRIX-STATUS.md composite line errors instead of guessing" {
  cat > "${BIN}/yq" <<'STUB'
#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in
    *excludes_flavor*) exit 0 ;;
    *enforcement*)     printf 'boots\nbuilds\ndesktop\n'; exit 0 ;;
    *flavors*)         printf 'green\n'; exit 0 ;;
    *emoji*)           printf 'sailfin\t🦈\n'; exit 0 ;;
  esac
done
exit 0
STUB
  chmod +x "${BIN}/yq"
  export MATRIX_STATUS_DOC="${BATS_TEST_TMPDIR}/absent-matrix-status.md"
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 1 ]
  [[ "$output" == *"carries no"* ]]
  grep -q 'stale' "$README"
}

# ── flag/arg handling and defaults ───────────────────────────────────────────

@test "args: an explicit config/readme pair is used verbatim" {
  local custom_config="${BATS_TEST_TMPDIR}/custom-config.yml"
  local custom_readme="${BATS_TEST_TMPDIR}/custom-README.md"
  echo 'variants: []' > "$custom_config"
  printf '<!-- build-status:start -->\nstale\n<!-- build-status:end -->\n' > "$custom_readme"

  run_generator "$custom_config" "$custom_readme"
  [ "$status" -eq 0 ]
  grep -q '\*\*1/4\*\*' "$custom_readme"
  # The default-named files, if present nearby, are left alone.
  [ ! -e "${BATS_TEST_TMPDIR}/README.md.bak" ]
}

@test "args: config and readme default to .github/build-config.yml and README.md in the cwd" {
  local work="${BATS_TEST_TMPDIR}/work"
  mkdir -p "${work}/.github"
  echo 'variants: []' > "${work}/.github/build-config.yml"
  printf '<!-- build-status:start -->\nstale\n<!-- build-status:end -->\n' > "${work}/README.md"

  run bash -c 'cd "$1" && shift && exec bash "$0"' "$SCRIPT" "$work"
  [ "$status" -eq 0 ]
  grep -q '\*\*1/4\*\*' "${work}/README.md"
}

@test "args: GITHUB_REPOSITORY defaults to tuna-os/tunaOS when unset" {
  unset GITHUB_REPOSITORY
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]
  grep -q -- '--repo tuna-os/tunaOS ' "$GH_LOG"
}

@test "args: GITHUB_REPOSITORY overrides the default repo used for every gh call" {
  export GITHUB_REPOSITORY="acme/widgets"
  run_generator "$CONFIG" "$README"
  [ "$status" -eq 0 ]
  grep -q -- '--repo acme/widgets ' "$GH_LOG"
  ! grep -q -- '--repo tuna-os/tunaOS ' "$GH_LOG"
}
