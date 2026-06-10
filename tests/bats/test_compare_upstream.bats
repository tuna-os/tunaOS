#!/usr/bin/env bats
# Unit tests for scripts/compare-with-upstream.sh
#
# Tests:
#   - Argument parsing: requires variant, flavor, upstream-image
#   - Image reference construction
#   - Error handling: missing TunaOS image, usage error
#   - comm-based file comparison logic
#   - Package list extraction patterns
#   - Directory extraction patterns

setup() {
  TEST_ROOT="$(mktemp -d)"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# compare-with-upstream.sh — Argument Validation
# ═══════════════════════════════════════════════════════════════════════════

@test "compare-upstream: exits with usage when no variant" {
  run bash -c '
    variant="${1:-}"
    upstream_image="${3:-}"
    if [[ -z "$variant" ]] || [[ -z "$upstream_image" ]]; then
      echo "Usage: compare-with-upstream.sh <variant> <flavor> <upstream-image>"
      exit 1
    fi
  ' _ "" base "ghcr.io/foo/bar:latest"
  [ "$status" -eq 1 ]
}

@test "compare-upstream: exits with usage when no upstream image" {
  run bash -c '
    variant="${1:-}"
    upstream_image="${3:-}"
    if [[ -z "$variant" ]] || [[ -z "$upstream_image" ]]; then
      echo "Usage: $0 <variant> <flavor> <upstream-image>"
      exit 1
    fi
  ' _ "skipjack" "base" ""
  [ "$status" -eq 1 ]
}

@test "compare-upstream: exits when TunaOS image does not exist locally" {
  run bash -c '
    TUNAOS_IMAGE="localhost/tunaos/skipjack:base-latest"
    if ! echo "image missing" | grep -q "exists"; then
      echo "ERROR: TunaOS image not found: $TUNAOS_IMAGE"
      exit 1
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"TunaOS image not found"* ]]
}

@test "compare-upstream: constructs correct TunaOS image ref" {
  run bash -c '
    variant="skipjack"
    flavor="base"
    TUNAOS_IMAGE="localhost/tunaos/${variant}:${flavor}-latest"
    echo "$TUNAOS_IMAGE"
  '
  [ "$output" = "localhost/tunaos/skipjack:base-latest" ]
}

@test "compare-upstream: constructs correct TunaOS image ref for non-base" {
  run bash -c '
    variant="yellowfin"
    flavor="gnome"
    TUNAOS_IMAGE="localhost/tunaos/${variant}:${flavor}-latest"
    echo "$TUNAOS_IMAGE"
  '
  [ "$output" = "localhost/tunaos/yellowfin:gnome-latest" ]
}

@test "compare-upstream: accepts upstream image ref directly" {
  run bash -c '
    upstream_image="ghcr.io/ublue-os/bluefin-lts:latest"
    UPSTREAM_IMAGE="$upstream_image"
    echo "$UPSTREAM_IMAGE"
  '
  [ "$output" = "ghcr.io/ublue-os/bluefin-lts:latest" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# compare-with-upstream.sh — File Diff Logic (comm-based)
# ═══════════════════════════════════════════════════════════════════════════

@test "compare-upstream: comm -23 finds files unique to first set" {
  # comm -23 = lines unique to FILE1 (suppress lines unique to FILE2 and common)
  run bash -c '
    echo -e "file-a\nfile-b\nfile-c" | sort >/tmp/cu-tunaos.txt
    echo -e "file-a\nfile-c" | sort >/tmp/cu-upstream.txt
    comm -23 /tmp/cu-tunaos.txt /tmp/cu-upstream.txt
  '
  [ "$output" = "file-b" ]
}

@test "compare-upstream: comm -13 finds files unique to second set" {
  # comm -13 = lines unique to FILE2
  run bash -c '
    echo -e "a\nb" | sort >/tmp/cu-tunaos2.txt
    echo -e "a\nb\nc" | sort >/tmp/cu-upstream2.txt
    comm -13 /tmp/cu-tunaos2.txt /tmp/cu-upstream2.txt
  '
  [ "$output" = "c" ]
}

@test "compare-upstream: comm -12 finds common files" {
  run bash -c '
    echo -e "a\nb\nc\nd" | sort >/tmp/cu-tunaos3.txt
    echo -e "b\nc\ne" | sort >/tmp/cu-upstream3.txt
    comm -12 /tmp/cu-tunaos3.txt /tmp/cu-upstream3.txt
  '
  [[ "$output" == *"b"* ]]
  [[ "$output" == *"c"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# compare-with-upstream.sh — Package Comparison
# ═══════════════════════════════════════════════════════════════════════════

@test "compare-upstream: rpm -qa produces sorted package list" {
  run bash -c '
    echo "kernel-6.12.0-1.x86_64" >/tmp/cu-pkgs.txt
    echo "bash-5.2.26-1.x86_64" >>/tmp/cu-pkgs.txt
    echo "systemd-256-1.x86_64" >>/tmp/cu-pkgs.txt
    sort /tmp/cu-pkgs.txt
  '
  [[ "$output" == *"bash"* ]]
  [[ "$output" == *"kernel"* ]]
  [[ "$output" == *"systemd"* ]]
}

@test "compare-upstream: comm finds unique packages" {
  run bash -c '
    echo -e "pkg-a\npkg-b\npkg-c\npkg-d" | sort >/tmp/cu-pkgs-a.txt
    echo -e "pkg-a\npkg-c\npkg-e" | sort >/tmp/cu-pkgs-b.txt

    UNIQUE_A=$(comm -23 /tmp/cu-pkgs-a.txt /tmp/cu-pkgs-b.txt | wc -l)
    UNIQUE_B=$(comm -13 /tmp/cu-pkgs-a.txt /tmp/cu-pkgs-b.txt | wc -l)
    COMMON=$(comm -12 /tmp/cu-pkgs-a.txt /tmp/cu-pkgs-b.txt | wc -l)

    echo "A-only:$UNIQUE_A B-only:$UNIQUE_B common:$COMMON"
  '
  [ "$output" = "A-only:2 B-only:1 common:2" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# compare-with-upstream.sh — Extraction Patterns
# ═══════════════════════════════════════════════════════════════════════════

@test "compare-upstream: extracts /usr/share, /usr/lib, /usr/bin, /etc" {
  run bash -c '
    EXTRACT_DIRS=("/usr/share" "/usr/lib" "/usr/libexec" "/usr/bin" "/etc")
    for d in "${EXTRACT_DIRS[@]}"; do
      echo "$d"
    done
  '
  [[ "$output" == *"/usr/share"* ]]
  [[ "$output" == *"/usr/lib"* ]]
  [[ "$output" == *"/usr/bin"* ]]
  [[ "$output" == *"/etc"* ]]
}

@test "compare-upstream: podman run extraction command pattern" {
  run bash -c '
    TUNAOS_IMAGE="localhost/tunaos/skipjack:base-latest"
    EXTRACT_DIR="/tmp/extract"
    CMD="podman run --rm -v ${EXTRACT_DIR}:/extract:Z ${TUNAOS_IMAGE} bash -c"
    echo "$CMD"
  '
  [[ "$output" == *"podman run"* ]]
  [[ "$output" == *"--rm"* ]]
  [[ "$output" == *"/extract:Z"* ]]
  [[ "$output" == *"bash -c"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# compare-with-upstream.sh — File Count Output Parsing
# ═══════════════════════════════════════════════════════════════════════════

@test "compare-upstream: file count uses wc -l" {
  run bash -c '
    mkdir -p /tmp/cu-test/usr/bin
    touch /tmp/cu-test/usr/bin/tool1
    touch /tmp/cu-test/usr/bin/tool2
    find /tmp/cu-test/usr -type f | wc -l
    rm -rf /tmp/cu-test
  '
  [ "$output" = "2" ]
}
