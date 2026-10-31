#!/usr/bin/env bats
# tunaOS#1702: "Run pytest tests" had no `if:` condition, so GitHub Actions'
# implicit `if: success()` skipped the entire pytest suite whenever the
# preceding BATS step failed. That silently masked Python regressions and
# left coverage-python.xml missing, which then made the "Upload Python
# coverage" step's "No files were found" warning look like the real failure
# in the failing-checks feed (~45 PRs), when the actual failure was BATS.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/test.yml"

@test "test.yml: Run pytest tests step runs even when BATS failed" {
  # Isolate the "Run pytest tests" step block up to the next "- name:".
  block="$(awk '/- name: Run pytest tests/,/- name: Test summary/' "$WORKFLOW")"
  [[ "$block" == *"if: always()"* ]]
}

@test "test.yml: Python coverage is uploaded to Codecov" {
  block="$(awk '/- name: Upload Python coverage to Codecov/,0' "$WORKFLOW")"
  [[ "$block" =~ codecov/codecov-action@[0-9a-f]{40} ]]
  [[ "$block" == *"use_oidc: true"* ]]
  [[ "$block" == *"files: coverage-python.xml"* ]]
  [[ "$block" == *"flags: python"* ]]
  [[ "$block" == *"fail_ci_if_error: false"* ]]
}

@test "test.yml: no job that runs repository code can mint an OIDC token (#3392)" {
  # Pull-request code runs in the test and build jobs, so none of them may hold
  # id-token: write, at workflow scope or job scope. Only the upload job may,
  # and it must execute no repository code.
  holders="$(yq -r '
    (.permissions["id-token"] // "none") as $top
    | .jobs | to_entries[]
    | select(((.value.permissions // {})["id-token"] // $top) == "write")
    | .key' "$WORKFLOW")"
  [ "$(yq -r '.permissions["id-token"] // "none"' "$WORKFLOW")" = none ]
  [ "$holders" = coverage-upload ]
  # tuna-pr-images.yml (moved out of test.yml, which now runs on merge_group):
  # tuna_pr_images and canary_cells (TUNA-2) are its only holders. Each only
  # calls the reusable build workflow (no steps), and GitHub gives fork pull
  # requests a read-only token without id-token.
  tuna="${REPO_ROOT}/.github/workflows/tuna-pr-images.yml"
  holders="$(yq -r '
    (.permissions["id-token"] // "none") as $top
    | .jobs | to_entries[]
    | select(((.value.permissions // {})["id-token"] // $top) == "write")
    | .key' "$tuna")"
  [ "$(yq -r '.permissions["id-token"] // "none"' "$tuna")" = none ]
  [ "$(printf '%s\n' "$holders" | sort | tr '\n' ' ')" = "canary_cells tuna_pr_images " ]
  [ "$(yq -r '.jobs.tuna_pr_images | has("steps")' "$tuna")" = false ]
  [ "$(yq -r '.jobs.canary_cells | has("steps")' "$tuna")" = false ]
  run yq -r '.jobs["coverage-upload"].steps[] | select(has("run")) | .name' "$WORKFLOW"
  [ -z "$output" ]
}

@test "test.yml: archived Python coverage ignores a missing coverage file" {
  block="$(awk '/- name: Archive Python coverage/,0' "$WORKFLOW")"
  [[ "$block" == *"if-no-files-found: ignore"* ]]
}

# Exercise the workflow shell itself: exit 255 is special to xargs (abort),
# and optional diagnostics must not decide whether the remaining files run.
prepare_parallel_bats_fixture() {
  FIXTURE="${BATS_TEST_TMPDIR}/parallel-bats"
  mkdir -p "$FIXTURE"/{bin,temp,records,tests/bats,reports}
  touch "$FIXTURE/tests/bats/"{a,b,c}.bats
  yq -r '.jobs["unit-tests"].steps[] | select(.name == "Run BATS tests") | .run' \
    "$WORKFLOW" > "$FIXTURE/runner"
  cat > "$FIXTURE/bin/bats" <<'BATS'
#!/usr/bin/env bash
file="${!#}"
printf '%s\n' "$TMPDIR" > "$BATS_RUNNER_RECORDS/${file##*/}"
printf '1..1\n'
if [[ "$file" == */b.bats ]]; then
  printf 'not ok 1 expected failure\n'
  exit 255
fi
printf 'ok 1 success\n'
BATS
  chmod +x "$FIXTURE/bin/bats"
  export PATH="$FIXTURE/bin:$PATH"
  export RUNNER_TEMP="$FIXTURE/temp"
  export BATS_RUNNER_RECORDS="$FIXTURE/records"
}

@test "test.yml: parallel BATS aggregates exit 255 without losing per-file reports" {
  prepare_parallel_bats_fixture
  export TEST_REPORT_ROOT="$FIXTURE/reports"
  run bash -c 'cd "$1" && bash runner' bash "$FIXTURE"
  [ "$status" -ne 0 ]
  [[ "$output" == *"expected failure"* ]]
  [[ "$output" == *"Running: tests/bats/c.bats"* ]]
  [ "$(cat "$FIXTURE/reports/bats/tests/bats/b.bats.tap.exit")" = 255 ]
  for file in a b c; do
    [ -s "$FIXTURE/records/$file.bats" ]
    [ -s "$FIXTURE/reports/bats/tests/bats/$file.bats.tap" ]
  done
  [ "$(cat "$FIXTURE/records/"*.bats | sort -u | wc -l)" -eq 3 ]
}

@test "test.yml: parallel BATS still runs every file without report storage" {
  prepare_parallel_bats_fixture
  export TEST_REPORT_ROOT=""
  run bash -c 'cd "$1" && bash runner' bash "$FIXTURE"
  [ "$status" -ne 0 ]
  [[ "$output" == *"expected failure"* ]]
  for file in a b c; do
    [ -s "$FIXTURE/records/$file.bats" ]
  done
}
