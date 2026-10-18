#!/usr/bin/env bats
# R2 publishing is a cost, so a build only pays it when someone wants the ISO.
#
# upload-r2 defaults to true in reusable-build-artifacts.yml, and for a long
# time build-variant.yml never overrode it. Every dispatch of a variant — every
# test build, every re-run chasing a red cell — therefore published each gated
# cell to R2. Each published cell writes its ISO TWICE, a dated object and the
# -latest pointer, so one variant's dispatch cost tens of GB of writes for
# artifacts nobody had asked for.
#
# The boot gate runs BEFORE the upload, so gating an ISO never needed one.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
VARIANT_WF="${REPO_ROOT}/.github/workflows/build-variant.yml"
ARTIFACTS_WF="${REPO_ROOT}/.github/workflows/reusable-build-artifacts.yml"
POLICY="${REPO_ROOT}/scripts/iso-delivery-policy.py"
CONFIG="${REPO_ROOT}/.github/build-config.yml"

setup() {
  TEST_TMPDIR="$(mktemp -d)"
}

teardown() {
  rm -rf "$TEST_TMPDIR"
}

@test "every ISO call site decides upload-r2 rather than inheriting the default" {
  local calls uploads
  calls=$(grep -c 'uses: ./.github/workflows/reusable-build-artifacts.yml' "$VARIANT_WF")
  uploads=$(grep -c '^      upload-r2:' "$VARIANT_WF")

  [ "$calls" -gt 0 ]
  [ "$calls" -eq "$uploads" ]
}

# A bare `true` here is the regression: it reinstates the old behaviour while
# looking deliberate.
@test "no ISO call site publishes unconditionally" {
  run grep -E '^      upload-r2: (true|.\{\{ true \}\})\s*$' "$VARIANT_WF"
  [ "$status" -ne 0 ]
}

@test "scheduled runs publish only outside reviewed cutover targets" {
  run grep -c "upload-r2: \${{ (github.event_name == 'schedule' || inputs.publish-isos) && !matrix.r2_cutover }}" "$VARIANT_WF"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "publish-isos exists as an opt-in and is off by default" {
  run grep -A9 '^      publish-isos:' "$VARIANT_WF"
  [ "$status" -eq 0 ]
  [[ "$output" == *"type: boolean"* ]]
  [[ "$output" == *"default: false"* ]]
}

# The whole argument for not publishing a test build is that the gate already
# ran. If the upload ever moved above the gate, an ungated ISO would ship.
@test "the boot gate runs before the R2 upload" {
  local gate upload
  gate=$(grep -n 'name: "Boot gate: verify ISO readiness"' "$ARTIFACTS_WF" | head -1 | cut -d: -f1)
  upload=$(grep -n 'name: Upload ISO to Cloudflare R2' "$ARTIFACTS_WF" | head -1 | cut -d: -f1)

  [ -n "$gate" ]
  [ -n "$upload" ]
  [ "$gate" -lt "$upload" ]
}

@test "the upload step is still guarded by the upload-r2 input" {
  run grep -A2 'name: Upload ISO to Cloudflare R2' "$ARTIFACTS_WF"
  [ "$status" -eq 0 ]
  [[ "$output" == *"if: inputs.upload-r2"* ]]
}

@test "the checked-in empty policy validates and keeps normal publication" {
  yq -o=json '.' "$CONFIG" > "$TEST_TMPDIR/config.json"
  run "$POLICY" --config-json "$TEST_TMPDIR/config.json" validate

  [ "$status" -eq 0 ]
  [[ "$output" == *"0 cutover target(s)"* ]]
}

@test "nonempty cutover remains disabled until qualification receipts are integrated" {
  cat > "$TEST_TMPDIR/config.json" <<'JSON'
{
  "iso_delivery": {
    "cutover_targets": [{
      "variant": "fish",
      "flavor": "gnome",
      "platform": "linux/amd64",
      "qualification": "browser-qualified",
      "qualified_at": "2026-10-18",
      "evidence": "qualification/fish-gnome.json"
    }],
    "retained_r2_isos": [
      "fish-gnome-latest.iso",
      "fish-gnome-20261018-x86_64.iso"
    ]
  },
  "iso_groups": [],
  "variants": [{
    "id": "fish",
    "platforms": ["linux/amd64"],
    "flavors": [
      {"id": "gnome", "build_image": true, "build_iso": true},
      {"id": "kde", "build_image": true, "build_iso": true}
    ]
  }]
}
JSON
  cat > "$TEST_TMPDIR/matrix.json" <<'JSON'
{"include":[
  {"variant":"fish","flavor":"gnome","platform":"linux/amd64"},
  {"variant":"fish","flavor":"kde","platform":"linux/amd64"}
]}
JSON

  run bash -c '"$1" --config-json "$2" annotate-target-matrix < "$3"' \
    _ "$POLICY" "$TEST_TMPDIR/config.json" "$TEST_TMPDIR/matrix.json"
  [ "$status" -ne 0 ]
  [[ "$output" == *"#3381"* ]]

  jq '.iso_delivery.cutover_targets = []' "$TEST_TMPDIR/config.json" \
    > "$TEST_TMPDIR/restored.json"
  run bash -c '"$1" --config-json "$2" annotate-target-matrix < "$3"' \
    _ "$POLICY" "$TEST_TMPDIR/restored.json" "$TEST_TMPDIR/matrix.json"
  [ "$status" -eq 0 ]
  [ "$(jq -r '[.include[].r2_cutover] | all(. == false)' <<<"$output")" = "true" ]
}

@test "retention protects each exact ISO and both verification sidecars" {
  cat > "$TEST_TMPDIR/config.json" <<'JSON'
{
  "iso_delivery": {
    "cutover_targets": [],
    "retained_r2_isos": ["fish-gnome-20261018-x86_64.iso"]
  },
  "iso_groups": [],
  "variants": []
}
JSON

  run "$POLICY" --config-json "$TEST_TMPDIR/config.json" retention-filters
  [ "$status" -eq 0 ]
  [[ "$output" == *"- /fish-gnome-20261018-x86_64.iso"* ]]
  [[ "$output" == *"- /fish-gnome-20261018-x86_64.iso.sha256"* ]]
  [[ "$output" == *"- /fish-gnome-20261018-x86_64.iso.sigstore.json"* ]]
}
