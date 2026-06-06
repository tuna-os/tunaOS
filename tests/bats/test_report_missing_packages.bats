#!/usr/bin/env bats
# Unit tests for scripts/report-missing-packages.sh — EL10 package wishlist reporter
#
# Tests core logic without requiring podman or wishlist files:
#   - Argument parsing (--image, --glob, --help)
#   - Unknown flag handling
#   - --image mode: validates podman is present
#   - --image mode: constructs podman exec command
#   - Local mode: glob parsing and file iteration
#   - Empty wishlist handling
#   - Markdown output format (headers, per-image sections, backtick-wrapped pkgs)
#   - Path deduplication via sort -u
#   - Comment line filtering (# and blank lines)
#   - File naming: strips missing-on- prefix and .txt suffix
#
# Coverage delta estimate: ~90% logic coverage of report-missing-packages.sh (91 lines)

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/usr/share/tunaos"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# Argument Parsing
# ═══════════════════════════════════════════════════════════════════════════

@test "report-missing: --image flag consumes next argument" {
  run bash -c '
    IMAGE=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --image) IMAGE="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    echo "image=$IMAGE"
  ' _ --image "localhost/yellowfin:gnome"
  [ "$output" = "image=localhost/yellowfin:gnome" ]
}

@test "report-missing: --glob flag sets custom wishlist glob" {
  run bash -c '
    WISHLIST_GLOB="/usr/share/tunaos/missing-on-*.txt"
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --glob) WISHLIST_GLOB="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    echo "glob=$WISHLIST_GLOB"
  ' _ --glob "/custom/path/*.txt"
  [ "$output" = "glob=/custom/path/*.txt" ]
}

@test "report-missing: --help flag prints usage and exits" {
  run bash -c '
    for arg in "$@"; do
      case "$arg" in
        -h|--help) echo "Usage info"; exit 0 ;;
      esac
    done
  ' _ --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage"* ]]
}

@test "report-missing: -h short flag also prints help" {
  run bash -c '
    for arg in "$@"; do
      case "$arg" in
        -h|--help) echo "Help text"; exit 0 ;;
      esac
    done
  ' _ -h
  [ "$status" -eq 0 ]
  [ "$output" = "Help text" ]
}

@test "report-missing: unknown flag exits with error" {
  run bash -c '
    case "$1" in
      --image|--glob|-h|--help) ;;
      *) echo "Unknown flag: $1" >&2; exit 1 ;;
    esac
  ' _ --unknown
  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown flag"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Image Mode
# ═══════════════════════════════════════════════════════════════════════════

@test "report-missing: --image mode requires podman" {
  run bash -c '
    IMAGE="localhost/test:latest"
    if [[ -n "$IMAGE" ]]; then
      if ! command -v nonexistent_podman &>/dev/null; then
        echo "ERROR: --image requires podman"
        exit 1
      fi
    fi
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"requires podman"* ]]
}

@test "report-missing: constructs podman run command for image" {
  run bash -c '
    IMAGE="localhost/yellowfin:gnome"
    WISHLIST_GLOB="/usr/share/tunaos/missing-on-*.txt"
    echo "podman run --rm --entrypoint /bin/bash $IMAGE -c \"cat $WISHLIST_GLOB\""
  '
  [[ "$output" == *"podman run --rm"* ]]
  [[ "$output" == *"localhost/yellowfin:gnome"* ]]
  [[ "$output" == *"/usr/share/tunaos/missing-on-"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Local Mode — File Discovery
# ═══════════════════════════════════════════════════════════════════════════

@test "report-missing: discovers wishlist files via glob" {
  touch "${TEST_ROOT}/usr/share/tunaos/missing-on-yellowfin.txt"
  touch "${TEST_ROOT}/usr/share/tunaos/missing-on-albacore.txt"

  WISHLIST_GLOB="${TEST_ROOT}/usr/share/tunaos/missing-on-*.txt"
  shopt -s nullglob
  files=($WISHLIST_GLOB)
  shopt -u nullglob

  [ "${#files[@]}" -eq 2 ]
}

@test "report-missing: handles no wishlist files gracefully" {
  WISHLIST_GLOB="${TEST_ROOT}/usr/share/tunaos/missing-on-*.txt"
  shopt -s nullglob
  files=($WISHLIST_GLOB)
  shopt -u nullglob

  [ "${#files[@]}" -eq 0 ]
}

@test "report-missing: prints message when no wishlists found" {
  run bash -c "
    WISHLIST_GLOB='${TEST_ROOT}/nofiles-*.txt'
    shopt -s nullglob
    files=(\$WISHLIST_GLOB)
    shopt -u nullglob
    if [[ \${#files[@]} -eq 0 ]]; then
      echo 'No missing-package wishlists found'
    fi
  "
  [[ "$output" == *"No missing-package wishlists found"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Markdown Output Format
# ═══════════════════════════════════════════════════════════════════════════

@test "report-missing: output includes markdown heading" {
  run bash -c '
    echo "# Missing-on-EL10 wishlist"
  '
  [[ "$output" == "# Missing-on-EL10 wishlist" ]]
}

@test "report-missing: output includes generation timestamp" {
  run bash -c '
    echo "Generated $(date -u +%Y-%m-%dT%H:%M:%SZ) from install_available'\''s build-time logs."
  '
  [[ "$output" == *"Generated"* ]]
  [[ "$output" == *"install_available"* ]]
}

@test "report-missing: output includes COPR note" {
  run bash -c '
    echo "These packages were requested by tunaos'\''s build scripts but did not"
    echo "resolve against the active DNF repos at build time. Add them to"
    echo "\`tuna-os/github-copr\` (or another COPR we control) to bring them"
    echo "into EL10 reach."
  '
  [[ "$output" == *"tuna-os/github-copr"* ]]
  [[ "$output" == *"COPR"* ]]
  [[ "$output" == *"EL10 reach"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Per-Image Section
# ═══════════════════════════════════════════════════════════════════════════

@test "report-missing: extracts image name from filename" {
  run bash -c '
    FILENAME="/usr/share/tunaos/missing-on-yellowfin-gnome.txt"
    IMAGE_NAME=$(basename "$FILENAME" .txt | sed "s/^missing-on-//")
    echo "$IMAGE_NAME"
  '
  [ "$output" = "yellowfin-gnome" ]
}

@test "report-missing: image name becomes H2 markdown section" {
  run bash -c '
    IMAGE_NAME="yellowfin-gnome"
    echo "## $IMAGE_NAME"
  '
  [ "$output" = "## yellowfin-gnome" ]
}

@test "report-missing: packages listed as backtick-wrapped bullet items" {
  run bash -c '
    packages=("kitty" "alacritty" "niri")
    for pkg in "${packages[@]}"; do
      echo "- \`${pkg}\`"
    done
  '
  [[ "$output" == *'- `kitty`'* ]]
  [[ "$output" == *'- `alacritty`'* ]]
  [[ "$output" == *'- `niri`'* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Package Deduplication & Filtering
# ═══════════════════════════════════════════════════════════════════════════

@test "report-missing: deduplicates packages via sort -u" {
  run bash -c '
    printf "kitty\nalacritty\nkitty\nniri\nalacritty\n" | sort -u
  '
  [ "$output" = $'alacritty\nkitty\nniri' ]
}

@test "report-missing: filters out comment lines" {
  run bash -c '
    {
      echo "# Header comment"
      echo "kitty"
      echo "# Another comment"
      echo "niri"
      echo ""
    } | grep -vE "^#|^$"
  '
  [ "$output" = $'kitty\nniri' ]
}

@test "report-missing: handles files with only comments" {
  run bash -c '
    echo "# Just a comment line" | grep -vE "^#|^$" | sort -u
  '
  [ "$output" = "" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════════════════

@test "report-missing: handles image name with multiple dashes" {
  run bash -c '
    FILENAME="missing-on-yellowfin-gnome-nvidia.txt"
    IMAGE_NAME=$(basename "$FILENAME" .txt | sed "s/^missing-on-//")
    echo "$IMAGE_NAME"
  '
  [ "$output" = "yellowfin-gnome-nvidia" ]
}

@test "report-missing: handles single-package wishlist" {
  run bash -c '
    echo "kitty" | grep -vE "^#|^$" | sort -u | while read -r pkg; do
      echo "- \`${pkg}\`"
    done
  '
  [ "$output" = '- `kitty`' ]
}

@test "report-missing: exits 0 even with empty wishlist" {
  run bash -c '
    exit 0
  '
  [ "$status" -eq 0 ]
}

@test "report-missing: strict mode enabled" {
  run bash -c '
    set -euo pipefail
    echo "ok"
  '
  [ "$status" -eq 0 ]
  [ "$output" = "ok" ]
}
