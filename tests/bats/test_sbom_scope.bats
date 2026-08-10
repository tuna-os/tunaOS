#!/usr/bin/env bats
# SBOM generation must describe the final image without making a large,
# layered source-based image unpublishable.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
WORKFLOW="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"

@test "SBOM scans the squashed image view" {
  run grep -E -- '--scope squashed' "$WORKFLOW"
  [ "$status" -eq 0 ]
  run grep -E -- '--scope all-layers' "$WORKFLOW"
  [ "$status" -ne 0 ]
}

@test "SBOM remains non-blocking and time-bounded" {
  grep -q '^        continue-on-error: true$' "$WORKFLOW"
  grep -q '^        timeout-minutes: 10$' "$WORKFLOW"
}
