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

@test "test.yml: Upload Python coverage step ignores a missing coverage file" {
  block="$(awk '/- name: Upload Python coverage/,0' "$WORKFLOW")"
  [[ "$block" == *"if-no-files-found: ignore"* ]]
}
