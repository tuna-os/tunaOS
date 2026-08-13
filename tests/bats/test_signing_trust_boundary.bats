#!/usr/bin/env bats
# Keyless signing must reject an unapproved workflow/ref, and untrusted
# (fork/PR) events must never be able to reach a signing job. Cosign itself
# enforces the identity/issuer check at verify time (tunaos#1187 acceptance
# criteria); these are the static, repo-checkable proxies for that: every
# certificate-identity is pinned to this exact workflow file (not a wildcard
# an attacker-controlled fork could satisfy), and every signing job's trigger
# excludes pull_request.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "reusable-build-image.yml sign job never runs on pull_request" {
  workflow="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"
  # The sign job's own if: condition, not just the caller's trigger — a
  # belt-and-suspenders check independent of how the workflow is invoked.
  grep -A5 '^  sign:' "$workflow" | grep -q "github.event_name != 'pull_request'"
}

@test "reusable-build-artifacts.yml and publish-iso-groups.yml are not pull_request-triggered" {
  # Both are workflow_call / workflow_dispatch only — a fork's pull_request
  # event cannot invoke either directly. (reusable-build-artifacts.yml is
  # only ever called from build-variant.yml, itself schedule/workflow_dispatch
  # only — see tunaos#1178.)
  run grep -A3 '^on:' "${REPO_ROOT}/.github/workflows/reusable-build-artifacts.yml"
  [[ "$output" != *"pull_request"* ]]

  run grep -A3 '^on:' "${REPO_ROOT}/.github/workflows/publish-iso-groups.yml"
  [[ "$output" != *"pull_request"* ]]
}

@test "every certificate-identity is pinned to its own exact workflow path" {
  # A wildcard or partial-match identity would let a signature from a
  # different workflow (e.g. an attacker's fork running under a similar
  # name) verify successfully. Each identity string must name the specific
  # .github/workflows/<file>.yml this job lives in.
  declare -A expect=(
    ["reusable-build-image.yml"]="reusable-build-image.yml"
    ["reusable-build-artifacts.yml"]="reusable-build-artifacts.yml"
    ["publish-iso-groups.yml"]="publish-iso-groups.yml"
  )
  for file in "${!expect[@]}"; do
    workflow="${REPO_ROOT}/.github/workflows/${file}"
    line=$(grep 'identity=' "$workflow")
    [[ -n "$line" ]]
    [[ "$line" == *".github/workflows/${expect[$file]}"* ]]
  done
}

@test "verify calls use the fixed GitHub Actions OIDC issuer, not a wildcard" {
  for file in reusable-build-image.yml reusable-build-artifacts.yml publish-iso-groups.yml; do
    workflow="${REPO_ROOT}/.github/workflows/${file}"
    grep -q 'issuer="https://token.actions.githubusercontent.com"' "$workflow"
    grep -q -- '--certificate-oidc-issuer "\$issuer"' "$workflow"
  done
}
