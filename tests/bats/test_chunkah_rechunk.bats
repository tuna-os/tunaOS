#!/usr/bin/env bats
# The rechunk→load handoff in scripts/build-image-inner.sh.
#
# tunaOS#1568: bonito's base build died at `podman load` with
#
#   archive/tar: invalid tar header
#
# after chunkah had printed "build complete". Three things were wrong around
# that, independent of whatever truncated the write:
#
#   1. CHUNKAH_IMAGE was hardcoded to quay.io/coreos/chunkah:latest, so an
#      upstream regression reached our builds unreviewed — while
#      registry-map.yaml had carried a digest pin for this image all along
#      that no caller could read (see test_registry_ref.bats).
#   2. The rpmdb branch — every RPM variant, bonito included — passed no
#      --prune, so chunkah packed the ostree object store into every image and
#      warned about it on every run.
#   3. Nothing looked at the archive before handing it to podman, so a
#      truncated write surfaced two steps later as an opaque tar error.
#
# These are shape assertions: the script drives podman against multi-GiB
# images and cannot be executed here.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
INNER_SH="${REPO_ROOT}/scripts/build-image-inner.sh"
REGISTRY_MAP="${REPO_ROOT}/registry-map.yaml"

@test "build-image-inner.sh is valid bash" {
  run bash -n "$INNER_SH"
  [ "$status" -eq 0 ]
}

# ── the chunkah image is pinned, not :latest ───────────────────────────────

@test "CHUNKAH_IMAGE resolves through registry-map.yaml, not a hardcoded tag" {
  run grep -F 'CHUNKAH_IMAGE="$(registry_ref coreos-chunkah)"' "$INNER_SH"
  [ "$status" -eq 0 ]
  # ^[^#]* so the comment explaining what was wrong doesn't satisfy the check.
  run grep -nE '^[^#]*CHUNKAH_IMAGE="quay\.io/coreos/chunkah:latest"' "$INNER_SH"
  [ "$status" -ne 0 ]
}

@test "registry-map.yaml pins coreos-chunkah to a digest" {
  # Extract the block by indentation rather than a fixed -A window, so adding
  # comment lines to the entry cannot silently stop the assertion from
  # reaching the digest.
  run awk '/^  coreos-chunkah:/{f=1;next} f&&/^  [a-z]/{exit} f' "$REGISTRY_MAP"
  [ "$status" -eq 0 ]
  [[ "$output" == *"digest: sha256:"* ]]
}

@test "renovate has a manager for registry-map.yaml digests" {
  # The previous pin was garbage-collected upstream (quay 404) because nothing
  # bumped it. A pin nothing maintains is a slow-motion build break.
  run grep -F 'registry-map' "${REPO_ROOT}/renovate.json"
  [ "$status" -eq 0 ]
}

# ── /sysroot pruning, with the slash that decides what it means ────────────

@test "chunkah prunes the ostree sysroot on BOTH rootfs branches" {
  # The rpmdb branch had no --prune at all, which is the branch bonito takes.
  # Code lines only: the comment above the block quotes the flag while
  # explaining it, and a count that included prose would pass on a file where
  # neither branch actually prunes.
  local n
  n="$(grep -cE '^[^#]*--prune /sysroot/' "$INNER_SH")"
  [ "$n" -eq 2 ]
}

@test "the sysroot prune keeps the directory itself (trailing slash)" {
  # chunkah src/scan.rs: "A trailing `/` means prune children only, keeping
  # the directory itself." Without the slash chunkah drops /sysroot itself —
  # the mountpoint a bootc image needs — so this is not cosmetic. Upstream's
  # own warning spells it "--prune /sysroot/".
  run grep -nE '^[^#]*--prune /sysroot([^/]|$)' "$INNER_SH"
  [ "$status" -ne 0 ]
}

@test "the existing rpmdb prune is preserved on the non-rpmdb branch" {
  # /var/lib/rpm is the dummy dir that branch creates so chunkah's rpmdb
  # loader succeeds; dropping it would pack the dummy into the image.
  run grep -F -- '--prune /var/lib/rpm' "$INNER_SH"
  [ "$status" -eq 0 ]
}

# ── the archive is checked before podman is asked to read it ───────────────

@test "the oci-archive is validated before podman load" {
  run grep -F 'validate_ociarchive' "$INNER_SH"
  [ "$status" -eq 0 ]
  # A zero exit from chunkah is not evidence: it printed "build complete" and
  # still produced the corrupt archive. The validator must actually walk the
  # tar headers, which is the read that failed.
  run grep -F 'tar tf' "$INNER_SH"
  [ "$status" -eq 0 ]
}

@test "validation runs before podman load, not after" {
  run awk '/^\tif chunkah_attempt .* && validate_ociarchive/{print NR; exit}' "$INNER_SH"
  local validate_line="$output"
  run awk '/podman load --input out\.ociarchive/{print NR; exit}' "$INNER_SH"
  local load_line="$output"
  [ -n "$validate_line" ]
  [ -n "$load_line" ]
  [ "$validate_line" -lt "$load_line" ]
}

@test "a corrupt archive fails the build instead of being loaded" {
  run awk '/rechunk_ok.*-ne 1/{f=1} f&&/^\texit 1/{print "found"; exit}' "$INNER_SH"
  [ "$output" = "found" ]
}

@test "the rechunk is retried once, on a fresh output directory" {
  run grep -F 'for attempt in 1 2; do' "$INNER_SH"
  [ "$status" -eq 0 ]
  # Attempt 2 must not validate attempt 1's corpse: the previous output dir is
  # removed and a new one made inside the loop.
  run awk '/for attempt in 1 2; do/{f=1} f&&/CHUNK_OUT=\$\(mktemp -d\)/{print "found"; exit}' "$INNER_SH"
  [ "$output" = "found" ]
  run awk '/for attempt in 1 2; do/{f=1} f&&/rm -rf "\$\{CHUNK_OUT\}"/{print "found"; exit}' "$INNER_SH"
  [ "$output" = "found" ]
}

@test "free space is reported around the rechunk" {
  # Disk pressure is the other candidate cause for a truncated write; one df
  # line either confirms or kills it the next time this fails.
  run grep -F 'df -Ph' "$INNER_SH"
  [ "$status" -eq 0 ]
}
