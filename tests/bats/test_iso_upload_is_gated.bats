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
  SNAPSHOT="$(mktemp)"
}

teardown() {
  rm -f "$POLICY" "$SNAPSHOT"
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

# emit_snapshot <outfile> [variant flavor platform]...
# Build a valid, qualified CatalogSnapshot matching the policy fixture. The
# currentInputs block is intentional: delivery-cutover.py must compare the
# snapshot with current observations before suppressing publication.
emit_snapshot() {
  local out="$1"
  shift
  python3 - "$out" "$@" <<'EOF'
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "scripts"))
from contracts.targets import _canonical_json, _oci_platform, cpu_baseline, hardware_scope

out, triples = sys.argv[1], sys.argv[2:]
assert len(triples) % 3 == 0, triples
digest = "sha256:" + "ab" * 32
entries = []
descriptors = {}
for variant, flavor, platform in zip(triples[0::3], triples[1::3], triples[2::3]):
    target = {
        "variant": variant,
        "flavor": flavor,
        "platform": platform,
        "cpuBaseline": cpu_baseline(variant, platform),
        "hardwareScope": hardware_scope(flavor),
    }
    key = f"{variant}:{flavor}:{platform}"
    pm = "sha256:" + (variant + flavor + platform).encode().hex()[:64].ljust(64, "0")
    entries.append({
        "target": target,
        "targetKey": key,
        "required": True,
        "scheduled": True,
        "publication": {
            "repository": f"ghcr.io/tuna-os/{variant}",
            "tag": flavor,
            "ref": f"ghcr.io/tuna-os/{variant}:{flavor}",
        },
        "availability": {"available": True, "ociPlatform": _oci_platform(platform)},
        "resolvedInputs": {
            "platformManifestDigest": pm,
            "indexDigest": None,
            "configDigest": None,
            "liveOverlayDigest": None,
            "liveOverlayBaseDigest": None,
            "installerRevision": "",
            "engineRevision": "",
        },
        "facts": {
            "digest": pm,
            "desktop": flavor.split("-")[0],
            "kernelVer": "",
            "hasSdBoot": False,
            "pkgManager": "",
            "repoFamily": "",
            "layerCount": 0,
            "compressedSize": 0,
            "bootc": True,
        },
        "qualification": {
            "status": "qualified",
            "reason": None,
            "qualifiedAt": "2026-10-01T00:00:00Z",
            "receiptDigest": digest,
            "browser": None,
            "resources": None,
        },
    })
    descriptors[key] = {"platform": platform, "platformManifestDigest": pm}
entries.sort(key=lambda entry: entry["targetKey"])
snapshot = {
    "schemaVersion": 1,
    "kind": "catalog-snapshot",
    "producerRevision": "bats-fixture",
    "generatedAt": "2026-10-01T00:00:00Z",
    "coverageDigest": "sha256:" + "03" * 32,
    "snapshotDigest": "sha256:" + hashlib.sha256(_canonical_json(entries)).hexdigest(),
    "targets": entries,
    "currentInputs": {"descriptors": descriptors, "overlays": {}, "pins": {}},
}
json.dump(snapshot, open(out, "w"), indent=2, sort_keys=True)
EOF
}


@test "a qualified target reports cut over (its R2 upload is suppressed)" {
  emit_policy "$POLICY" bonito gnome linux/amd64
  emit_snapshot "$SNAPSHOT" bonito gnome linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]
}

@test "a qualified policy without a snapshot refuses suppression" {
  emit_policy "$POLICY" bonito gnome linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]
}


@test "an unqualified target reports not cut over (publication continues)" {
  emit_policy "$POLICY" bonito gnome linux/amd64
  emit_snapshot "$SNAPSHOT" bonito gnome linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/arm64 \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]

  run python3 "$CUTOVER" --check \
    --variant bonito --flavor kde --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]
}


@test "an empty policy cuts over nothing (current behavior)" {
  emit_policy "$POLICY"
  emit_snapshot "$SNAPSHOT" \
    bonito gnome linux/amd64 \
    yellowfin kde linux/amd64/v2 \
    yellowfin kde linux/arm64 \
    yellowfin kde-hwe linux/amd64/v2 \
    yellowfin kde-hwe linux/arm64 \
    yellowfin kde-nvidia linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
  [ "$status" -eq 1 ]
  [ "$output" = "false" ]

  run python3 "$CUTOVER" --check \
    --variant yellowfin --group kde \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
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
  emit_snapshot "$SNAPSHOT" \
    yellowfin kde linux/amd64/v2 \
    yellowfin kde linux/arm64 \
    yellowfin kde-hwe linux/amd64/v2 \
    yellowfin kde-nvidia linux/amd64
  run python3 "$CUTOVER" --check \
    --variant yellowfin --group kde \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
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
  emit_snapshot "$SNAPSHOT" \
    yellowfin kde linux/amd64/v2 \
    yellowfin kde linux/arm64 \
    yellowfin kde-hwe linux/amd64/v2 \
    yellowfin kde-hwe linux/arm64 \
    yellowfin kde-nvidia linux/amd64
  run python3 "$CUTOVER" --check \
    --variant yellowfin --group kde \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
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
  emit_snapshot "$SNAPSHOT" \
    bonito gnome linux/amd64 \
    bonito gnome linux/arm64 \
    bonito gnome-hwe linux/amd64 \
    bonito gnome-hwe linux/arm64 \
    bonito gnome-nvidia linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --group default \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]

  run python3 "$CUTOVER" --check \
    --variant bonito --group flagship \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]
}


@test "removing the cutover entry restores publication (rollback)" {
  emit_policy "$POLICY" bonito gnome linux/amd64
  emit_snapshot "$SNAPSHOT" bonito gnome linux/amd64
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]

  # The entry is cut from the policy; the previous path returns.
  emit_policy "$POLICY"
  run python3 "$CUTOVER" --check \
    --variant bonito --flavor gnome --platform linux/amd64 \
    --policy "$POLICY" --config "$CONFIG" --snapshot "$SNAPSHOT"
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
  run grep -F "scripts/delivery-cutover.py" "${REPO_ROOT}/.github/workflows/publish-isos.yml"
  [ "$status" -eq 0 ]
  run grep -F -- "--annotate-matrix" "${REPO_ROOT}/.github/workflows/publish-isos.yml"
  [ "$status" -eq 0 ]
  run grep -F "cutover-check:" "${REPO_ROOT}/.github/workflows/build-variant.yml"
  [ "$status" -eq 0 ]
}

# Upstream wiring (kept from main): every ISO call site still decides
# upload-r2 explicitly, scheduled runs still publish, and the boot gate
# still runs before the R2 upload. The cutover gate above only suppresses
# the upload inside reusable-build-artifacts.yml; it never reorders it.

@test "every ISO call site decides upload-r2 rather than inheriting the default" {
  local wf="${REPO_ROOT}/.github/workflows/build-variant.yml"
  local calls uploads
  calls=$(grep -c 'uses: ./.github/workflows/reusable-build-artifacts.yml' "$wf")
  uploads=$(grep -c '^      upload-r2:' "$wf")

  [ "$calls" -gt 0 ]
  [ "$calls" -eq "$uploads" ]
}

@test "no ISO call site publishes unconditionally" {
  local wf="${REPO_ROOT}/.github/workflows/build-variant.yml"
  run grep -E '^      upload-r2: (true|.\{\{ true \}\})\s*$' "$wf"
  [ "$status" -ne 0 ]
}

@test "scheduled runs still publish, so documented download URLs stay current" {
  local wf="${REPO_ROOT}/.github/workflows/build-variant.yml"
  run grep -c "upload-r2: \${{ github.event_name == 'schedule' || inputs.publish-isos }}" "$wf"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "the boot gate runs before the R2 upload" {
  local wf="${REPO_ROOT}/.github/workflows/reusable-build-artifacts.yml"
  local gate upload
  gate=$(grep -n 'name: "Boot gate: verify ISO readiness"' "$wf" | head -1 | cut -d: -f1)
  upload=$(grep -n 'name: Upload ISO to Cloudflare R2' "$wf" | head -1 | cut -d: -f1)

  [ -n "$gate" ]
  [ -n "$upload" ]
  [ "$gate" -lt "$upload" ]
}
