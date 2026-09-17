#!/usr/bin/env bats
# The NVIDIA audit must check the channel ISOs are actually published to.
#
# The original version asked GitHub Releases for a per-flavor tag carrying at
# least one asset. It was red on all 15 runs it ever had, and could not have
# been anything else:
#
#   * reusable-build-artifacts.yml's `attach-release` input DEFAULTS TO FALSE,
#     so "Attach ISO to GitHub Release" is skipped on every cell while
#     "Upload ISO to Cloudflare R2" succeeds beside it.
#   * The releases that exist are per desktop (gnome-20260916), not per
#     flavor, so no tag started with "gnome-nvidia-".
#   * Those releases carry 0 assets.
#
# A gate that cannot pass reports nothing, and this one also asked about
# `gnome50-nvidia`, a flavor in no variant of .github/build-config.yml.
#
# These tests are hermetic: they stub yq and rclone and point the script at a
# fixture config, so they do not depend on which yq the runner ships (Ubuntu's
# `yq` is a different program from the mikefarah one CI installs).

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/scripts/audit-nvidia-release-assets.sh"
  STUB="$(mktemp -d)"
  FIX="$(mktemp -d)"

  cat >"${STUB}/yq" <<'EOF'
#!/bin/sh
for a in "$@"; do last="$a"; done
python3 -c "import yaml,json,sys;print(json.dumps(yaml.safe_load(open(sys.argv[1]))))" "$last"
EOF
  cat >"${STUB}/rclone" <<'EOF'
#!/bin/sh
cat "$LISTING"
EOF
  chmod +x "${STUB}/yq" "${STUB}/rclone"

  cat >"${FIX}/build-config.yml" <<'EOF'
variants:
  - id: yellowfin
    flavors:
      - id: gnome-nvidia
        build_image: true
        build_iso: true
      - id: base-nvidia
        build_image: true
        build_iso: false
      - id: gnome
        build_image: true
        build_iso: true
EOF
}

teardown() { rm -rf "$STUB" "$FIX"; }

run_audit() {
  run env PATH="${STUB}:$PATH" \
    TUNAOS_BUILD_CONFIG="${FIX}/build-config.yml" \
    LISTING="$1" \
    RCLONE_CONFIG_R2_ACCESS_KEY_ID=key \
    R2_BUCKET=bucket \
    bash "$SCRIPT"
}

@test "it passes when every advertised NVIDIA ISO is in R2" {
  printf 'yellowfin-gnome-nvidia-latest.iso\n' >"${FIX}/listing"
  run_audit "${FIX}/listing"
  [ "$status" -eq 0 ]
  [[ "$output" == *"AUDIT PASSED"* ]]
}

@test "it fails and names the cell when an ISO is absent" {
  : >"${FIX}/listing"
  run_audit "${FIX}/listing"
  [ "$status" -eq 1 ]
  [[ "$output" == *"yellowfin-gnome-nvidia-latest.iso"* ]]
}

# build_iso: false means the matrix never promises a download, so demanding
# one would make the audit permanently red again — the exact original bug.
@test "a flavor that builds no ISO is not demanded" {
  printf 'yellowfin-gnome-nvidia-latest.iso\n' >"${FIX}/listing"
  run_audit "${FIX}/listing"
  [ "$status" -eq 0 ]
  [[ "$output" != *"base-nvidia"* ]]
}

@test "non-NVIDIA flavors are out of scope" {
  printf 'yellowfin-gnome-nvidia-latest.iso\n' >"${FIX}/listing"
  run_audit "${FIX}/listing"
  [[ "$output" != *"yellowfin-gnome-latest.iso"* ]]
}

# A fork has no R2 credentials. Failing there reports a fault that does not
# exist; the upload step and prune-r2.yml both skip on the same condition.
@test "absent R2 credentials skip rather than fail" {
  run env -u RCLONE_CONFIG_R2_ACCESS_KEY_ID -u R2_BUCKET \
    PATH="${STUB}:$PATH" \
    TUNAOS_BUILD_CONFIG="${FIX}/build-config.yml" \
    bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"not configured"* ]]
}

# THE DRIFT GUARD. The old list was hardcoded and had already drifted:
# `gnome50-nvidia` existed in the audit and in no variant. Deriving the cells
# from build-config.yml is what stops that recurring.
@test "the cell list is derived from build-config, not hardcoded" {
  run grep -E '^[^#]*gnome50-nvidia' "$SCRIPT"
  [ "$status" -ne 0 ]
  run grep -F 'build-config.yml' "$SCRIPT"
  [ "$status" -eq 0 ]
}

# It must not go back to asking GitHub Releases.
@test "it audits R2 and not GitHub releases" {
  run grep -E '^[^#]*live-isos/' "$SCRIPT"
  [ "$status" -eq 0 ]
  run grep -E '^[^#]*(gh api|releases\?per_page)' "$SCRIPT"
  [ "$status" -ne 0 ]
}
