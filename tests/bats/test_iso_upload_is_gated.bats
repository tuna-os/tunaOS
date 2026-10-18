#!/usr/bin/env bats
# Per-target delivery cutover (delivery-cutover.json) gates R2 ISO uploads.
#
# A build always runs — build, boot gate and signing are untouched — but the
# R2 upload for a {variant, flavor, platform} cell is suppressed once that
# target is cut over, and a grouped ISO stops publishing once EVERY live +
# offline member target is cut over. With the empty initial policy every gate
# evaluates to today's behavior (uploads proceed), and removing a cutover
# entry restores publication (rollback).
#
# These are behavioral tests: they run scripts/delivery-cutover.py --check
# (the same entry point the workflows call) against crafted policies and
# assert the suppression signal, not grep hits. A small set of wiring checks
# at the bottom pins where the signal is consumed.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
CUTOVER="${REPO_ROOT}/scripts/delivery-cutover.py"
CONFIG="${REPO_ROOT}/.github/build-config.yml"
DIGEST="sha256:abababababababababababababababababababababababababababababababab"

setup() {
  POLICY="$(mktemp)"
}

teardown() {
  rm -f "$POLICY"
}

# emit_policy <outfile> [variant flavor platform]...
# Writes a DeliveryPolicy v1 with one bound evidence entry per triple.
emit_policy() {
  local out="$1"
  shift
  python3 - "$out" "$@" <<'EOF'
import json, sys
out, triples = sys.argv[1], sys.argv[2:]
assert len(triples) % 3 == 0, triples
digest = "sha256:" + "ab" * 32
entries = [
    {"target": {"variant": v, "flavor": f, "platform": p},
     "evidence": {"receiptDigest": digest, "qualifiedAt": "2026-10-01T00:00:00Z"},
     "preset": "bats-fixture"}
    for v, f, p in zip(triples[0::3], triples[1::3], triples[2::3])
]
json.dump({"schemaVersion": 1, "kind": "delivery-cutover",
           "cutover": entries, "retained": []}, open(out, "w"))
EOF
}

@test "a qualified target reports cut over (its R2 upload is suppressed)" {
  emit_policy "$POLICY" bonito gnome linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]
}

@test "an unqualified target reports not cut over (publication continues)" {
  emit_policy "$POLICY" bonito gnome linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/arm64 \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]

  run python3 "$CUTOVER" --check \
    --variant bonito --flavor kde --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]
}

@test "an empty policy cuts over nothing (current behavior)" {
  emit_policy "$POLICY"
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]

  run python3 "$CUTOVER" --check \
    --variant yellowfin --group kde \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]
}

# The yellowfin kde group resolves to kde x {v2, arm64}, kde-hwe x {v2,
# arm64} and kde-nvidia x {amd64}: five member targets, all required.
@test "partial group closure does not suppress the grouped upload" {
  emit_policy "$POLICY" \
    yellowfin kde linux/amd64/v2 \
    yellowfin kde linux/arm64 \
    yellowfin kde-hwe linux/amd64/v2 \
    yellowfin kde-nvidia linux/amd64
  run python3 "$CUTOVER" --check \
    --variant yellowfin --group kde \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]
}

@test "complete group closure suppresses the grouped upload" {
  emit_policy "$POLICY" \
    yellowfin kde linux/amd64/v2 \
    yellowfin kde linux/arm64 \
    yellowfin kde-hwe linux/amd64/v2 \
    yellowfin kde-hwe linux/arm64 \
    yellowfin kde-nvidia linux/amd64
  run python3 "$CUTOVER" --check \
    --variant yellowfin --group kde \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]
}

@test "flagship group aliases resolve the same closure" {
  emit_policy "$POLICY" \
    bonito gnome linux/amd64 \
    bonito gnome linux/arm64 \
    bonito gnome-hwe linux/amd64 \
    bonito gnome-hwe linux/arm64 \
    bonito gnome-nvidia linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --group default \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]

  run python3 "$CUTOVER" --check \
    --variant bonito --group flagship \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]
}

@test "removing the cutover entry restores publication (rollback)" {
  emit_policy "$POLICY" bonito gnome linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]

  # The entry is cut from the policy; the previous path returns.
  emit_policy "$POLICY"
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]
}

# Wiring: where the suppression signal is consumed. Behavioral tests above
# prove the signal; these pin the call sites so a workflow refactor that
# drops the gate fails loudly instead of silently publishing again.

@test "the artifact build takes a cutover gate defaulting to current behavior" {
  run grep -F -c "cutover-check:" "${REPO_ROOT}/.github/workflows/reusable-build-artifacts.yml"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
  run grep -F -A12 "cutover-check:" "${REPO_ROOT}/.github/workflows/reusable-build-artifacts.yml"
  [[ "$output" == *"default: false"* ]]
  run grep -F "CUTOVER_SUPPRESS" "${REPO_ROOT}/.github/workflows/reusable-build-artifacts.yml"
  [ "$status" -eq 0 ]
}

@test "the grouped ISO upload is gated on group closure" {
  run grep -F "steps.cutover.outputs.cutover != 'true'" "${REPO_ROOT}/.github/workflows/publish-iso-groups.yml"
  [ "$status" -eq 0 ]
}

@test "the prune consults the retained inventory for its exclusions" {
  run grep -F "scripts/delivery-cutover.py --retained" "${REPO_ROOT}/.github/workflows/prune-r2.yml"
  [ "$status" -eq 0 ]
  run grep -F '"${KEPT[@]}"' "${REPO_ROOT}/.github/workflows/prune-r2.yml"
  [ "$status" -eq 0 ]
}

@test "the matrix callers stamp per-row cutover state" {
  run grep -F "scripts/delivery-cutover.py --annotate-matrix" "${REPO_ROOT}/.github/workflows/build-variant.yml"
  [ "$status" -eq 0 ]
  run grep -F "scripts/delivery-cutover.py --annotate-matrix" "${REPO_ROOT}/.github/workflows/publish-isos.yml"
  [ "$status" -eq 0 ]
  run grep -F "cutover-check:" "${REPO_ROOT}/.github/workflows/build-variant.yml"
  [ "$status" -eq 0 ]
}
