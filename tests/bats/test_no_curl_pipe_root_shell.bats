#!/usr/bin/env bats
# No workflow pipes a remote script into a root shell (tunaOS#1327).
#
# #1327 was filed against tuna-os/tunaos-packages, where 15 workflows ran
#
#     curl -fsSL https://rclone.org/install.sh | sudo bash
#
# and it was fixed there (tunaos-packages#373). It was filed per-vendor,
# though, so nothing looked for the same shape elsewhere — and this repo had
# it too, with a different vendor:
#
#     || curl -fsSL https://just.systems/install.sh | sudo bash -s -- --to /usr/local/bin
#
# in reusable-build-image.yml's "Install just and yq" step. Worse than the
# rclone one in one respect: it was a FALLBACK behind a pinned download, so the
# unpinned root shell ran exactly when the pinned path had already failed, and
# the pinned curl's stderr was sent to /dev/null so nobody saw why.
#
# The runner holds R2 keys and GHCR push credentials, so root code execution
# there is not a theoretical grade of bad.
#
# This test is the generalisation the issue lacked: the shape, not the vendor.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# Any `curl`/`wget` whose output is piped into a shell. Deliberately matches
# `| bash`, `| sh`, and the sudo forms — piping into a non-root shell on a
# runner that has passwordless sudo is barely better.
PIPE_TO_SHELL='(curl|wget)[^|;&]*\|[[:space:]]*(sudo[[:space:]]+)?(bash|sh)([[:space:]]|$)'

@test "no workflow pipes a downloaded script into a shell" {
  run grep -rInE "$PIPE_TO_SHELL" "${REPO_ROOT}/.github/workflows"
  # grep exits 1 on no match, which is the passing case. Print what it found so
  # a failure names the file and line rather than just going red.
  if [ "$status" -eq 0 ]; then
    echo "curl|shell found in workflows:" >&2
    echo "$output" >&2
  fi
  [ "$status" -ne 0 ]
}

@test "no build or helper script pipes a downloaded script into a shell" {
  # _upstream-snapshots/ is vendored third-party source, not ours to rewrite.
  run bash -c "grep -rInE '$PIPE_TO_SHELL' \
      --include='*.sh' --include='Justfile' --include='Containerfile*' \
      '${REPO_ROOT}/scripts' '${REPO_ROOT}/build_scripts' '${REPO_ROOT}/Justfile' 2>/dev/null"
  if [ "$status" -eq 0 ]; then
    echo "curl|shell found:" >&2
    echo "$output" >&2
  fi
  [ "$status" -ne 0 ]
}

# ── the replacement is verified, not merely pinned ────────────────────────

@test "the just/yq installer checksums what it downloads" {
  local wf="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"
  # A version pin still trusts the bytes the CDN returns. Both downloads must
  # be checked before install.
  run grep -c 'sha256sum -c -' "$wf"
  [ "$status" -eq 0 ]
  [ "$output" -ge 2 ]
}

@test "the just/yq installer verifies before writing anything root-owned" {
  # The old step did `sudo wget -qO /usr/bin/yq ...`, so unverified bytes became
  # a system binary before any check could object. Downloads must land in /tmp.
  local wf="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"
  run grep -nE '^\s*sudo (wget|curl)' "$wf"
  [ "$status" -ne 0 ]
}

@test "an architecture with no pinned checksum fails instead of guessing" {
  # Silently continuing on an unknown arch would reintroduce the hole on the
  # exact runner nobody tested.
  local wf="${REPO_ROOT}/.github/workflows/reusable-build-image.yml"
  run grep -F 'no pinned yq/just checksum for' "$wf"
  [ "$status" -eq 0 ]
}
