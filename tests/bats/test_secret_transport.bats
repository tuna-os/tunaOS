#!/usr/bin/env bats
# Credentials interpolated into URLs are persisted in git remotes and can
# leak through diagnostics, process listings, or error output. Keep workflow
# authentication transport-safe even when a future private checkout is added.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOWS="${REPO_ROOT}/.github/workflows"

@test "active workflows do not interpolate repository secrets into URLs" {
  run grep -R -E \
    'https?://[^[:space:]]*\$\{\{[[:space:]]*secrets\.' \
    "$WORKFLOWS" --exclude-dir=archive
  [ "$status" -ne 0 ]
}

@test "active workflows do not interpolate token variables into URLs" {
  run grep -R -E \
    'https?://[^[:space:]]*\$\{[A-Za-z_][A-Za-z0-9_]*TOKEN\}' \
    "$WORKFLOWS" --exclude-dir=archive
  [ "$status" -ne 0 ]
}
