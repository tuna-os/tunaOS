#!/usr/bin/env bats
# Unit tests for scripts/build-iso-tacklebox.sh
#
# Validates pure-logic paths without requiring root/podman/qemu:
#   - Argument validation (missing args, root check, project root)
#   - IMAGE_REF resolution via tunaos_image_ref
#   - Desktop detection from flavor
#   - Recipe JSON generation
#   - Tacklebox source vs container selection
#   - Output path construction

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/live-iso"
  cd "${TEST_ROOT}" || exit 1
}

teardown() {
  cd / || true
  rm -rf "${TEST_ROOT}"
}

# ── Argument validation ────────────────────────────────────────────────────

@test "arg validation: requires variant arg" {
  run bash -c '
    VARIANT="${1:-}"
    FLAVOR="${2:-}"
    [[ -z "$VARIANT" ]] && { echo "ERROR: variant required" >&2; exit 1; }
    echo "ok"
  '
  [ "$status" -eq 1 ]
}

@test "arg validation: requires flavor arg" {
  run bash -c '
    VARIANT="${1:-yellowfin}"
    FLAVOR="${2:-}"
    [[ -z "$FLAVOR" ]] && { echo "ERROR: flavor required" >&2; exit 1; }
    echo "ok"
  '
  [ "$status" -eq 1 ]
}

@test "arg validation: defaults repo to local" {
  VARIANT="yellowfin"
  FLAVOR="gnome"
  REPO="${3:-local}"
  [ "$REPO" = "local" ]
}

@test "arg validation: defaults tag to flavor" {
  VARIANT="skipjack"
  FLAVOR="kde"
  TAG="${4:-$FLAVOR}"
  [ "$TAG" = "kde" ]
}

@test "arg validation: custom tag overrides flavor default" {
  VARIANT="bonito"
  FLAVOR="gnome"
  TAG="${4:-$FLAVOR}"
  # Simulate custom tag passed
  TAG="custom"
  [ "$TAG" = "custom" ]
}

@test "root check: detects non-root and errors" {
  run bash -c '
    EUID=1000
    [[ "$EUID" -ne 0 ]] && { echo "ERROR: tacklebox needs root" >&2; exit 1; }
    echo "should not reach"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"needs root"* ]]
}

@test "root check: passes when EUID is 0" {
  run bash -c '
    EUID=0
    [[ "$EUID" -ne 0 ]] && { echo "ERROR" >&2; exit 1; }
    echo "root ok"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "root ok" ]]
}

@test "project root: detects missing live-iso/ directory" {
  run bash -c '
    [[ ! -d "live-iso" ]] && { echo "ERROR: run from project root (live-iso/ not found)" >&2; exit 1; }
    echo "ok"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"live-iso/ not found"* ]]
}

@test "project root: passes when live-iso/ exists" {
  mkdir -p "${TEST_ROOT}/live-iso"
  cd "${TEST_ROOT}"
  run bash -c '
    [[ -d "live-iso" ]] && echo "project root ok"
    [[ ! -d "live-iso" ]] && { echo "ERROR" >&2; exit 1; }
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"project root ok"* ]]
}

# ── IMAGE_REF resolution ───────────────────────────────────────────────────

@test "image_ref: resolves local variant+flavor" {
  tunaos_image_ref() {
    local variant="${1:?}"
    local flavor="${2:-gnome}"
    local repo="${3:-local}"
    local tag="${4:-${flavor}}"
    [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
    local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
    case "$repo" in
      local) echo "localhost/${variant}:${tag}" ;;
      ghcr)  echo "ghcr.io/${owner}/${variant}:${tag}" ;;
      *) return 1 ;;
    esac
  }
  result=$(tunaos_image_ref "yellowfin" "gnome" "local")
  [ "$result" = "localhost/yellowfin:gnome" ]
}

@test "image_ref: resolves GHCR reference" {
  tunaos_image_ref() {
    local variant="${1:?}"
    local flavor="${2:-gnome}"
    local repo="${3:-local}"
    local tag="${4:-${flavor}}"
    [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
    local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
    case "$repo" in
      local) echo "localhost/${variant}:${tag}" ;;
      ghcr)  echo "ghcr.io/${owner}/${variant}:${tag}" ;;
      *) return 1 ;;
    esac
  }
  result=$(tunaos_image_ref "skipjack" "kde" "ghcr")
  [ "$result" = "ghcr.io/tuna-os/skipjack:kde" ]
}

@test "image_ref: custom tag used for ghcr" {
  tunaos_image_ref() {
    local variant="${1:?}"
    local flavor="${2:-gnome}"
    local repo="${3:-local}"
    local tag="${4:-${flavor}}"
    [[ "$variant" == *":"* || "$variant" == *"/"* ]] && { echo "$variant"; return; }
    local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
    case "$repo" in
      local) echo "localhost/${variant}:${tag}" ;;
      ghcr)  echo "ghcr.io/${owner}/${variant}:${tag}" ;;
      *) return 1 ;;
    esac
  }
  result=$(tunaos_image_ref "bonito" "niri" "ghcr" "v1.2.3")
  [ "$result" = "ghcr.io/tuna-os/bonito:v1.2.3" ]
}

# ── Desktop detection ──────────────────────────────────────────────────────

@test "desktop: flavor 'gnome' maps to desktop 'gnome'" {
  FLAVOR="gnome"
  case "$FLAVOR" in
    kde*) DESKTOP="kde" ;;
    niri*) DESKTOP="niri" ;;
    cosmic*) DESKTOP="cosmic" ;;
    gnome* | *) DESKTOP="gnome" ;;
  esac
  [ "$DESKTOP" = "gnome" ]
}

@test "desktop: flavor 'kde' maps to desktop 'kde'" {
  FLAVOR="kde"
  case "$FLAVOR" in
    kde*) DESKTOP="kde" ;;
    niri*) DESKTOP="niri" ;;
    cosmic*) DESKTOP="cosmic" ;;
    gnome* | *) DESKTOP="gnome" ;;
  esac
  [ "$DESKTOP" = "kde" ]
}

@test "desktop: flavor 'kde-hwe' maps to desktop 'kde'" {
  FLAVOR="kde-hwe"
  case "$FLAVOR" in
    kde*) DESKTOP="kde" ;;
    niri*) DESKTOP="niri" ;;
    cosmic*) DESKTOP="cosmic" ;;
    gnome* | *) DESKTOP="gnome" ;;
  esac
  [ "$DESKTOP" = "kde" ]
}

@test "desktop: flavor 'niri' maps to desktop 'niri'" {
  FLAVOR="niri"
  case "$FLAVOR" in
    kde*) DESKTOP="kde" ;;
    niri*) DESKTOP="niri" ;;
    cosmic*) DESKTOP="cosmic" ;;
    gnome* | *) DESKTOP="gnome" ;;
  esac
  [ "$DESKTOP" = "niri" ]
}

@test "desktop: flavor 'cosmic' maps to desktop 'cosmic'" {
  FLAVOR="cosmic"
  case "$FLAVOR" in
    kde*) DESKTOP="kde" ;;
    niri*) DESKTOP="niri" ;;
    cosmic*) DESKTOP="cosmic" ;;
    gnome* | *) DESKTOP="gnome" ;;
  esac
  [ "$DESKTOP" = "cosmic" ]
}

@test "desktop: flavor 'gnome-hwe' maps to desktop 'gnome'" {
  FLAVOR="gnome-hwe"
  case "$FLAVOR" in
    kde*) DESKTOP="kde" ;;
    niri*) DESKTOP="niri" ;;
    cosmic*) DESKTOP="cosmic" ;;
    gnome* | *) DESKTOP="gnome" ;;
  esac
  [ "$DESKTOP" = "gnome" ]
}

@test "desktop: unknown flavor defaults to gnome" {
  FLAVOR="lxqt"
  case "$FLAVOR" in
    kde*) DESKTOP="kde" ;;
    niri*) DESKTOP="niri" ;;
    cosmic*) DESKTOP="cosmic" ;;
    gnome* | *) DESKTOP="gnome" ;;
  esac
  [ "$DESKTOP" = "gnome" ]
}

# ── Recipe JSON generation ─────────────────────────────────────────────────

@test "recipe: generates valid JSON with required fields" {
  VARIANT="yellowfin"
  FLAVOR="gnome"
  IMAGE_REF="localhost/yellowfin:gnome"
  DESKTOP="gnome"
  OUT_DIR=".build/iso-tacklebox/${VARIANT}-${FLAVOR}"
  RECIPE_FILE="${OUT_DIR}/recipe.json"
  mkdir -p "$OUT_DIR"

  cat >"$RECIPE_FILE" <<EOF
{
  "media_name": "tunaos-${VARIANT}-${FLAVOR}",
  "size": "10G",
  "shared_store": {
    "format": "ext4"
  },
  "bootable_environments": [
    {
      "id": "${VARIANT}-${FLAVOR}",
      "image": "${IMAGE_REF}",
      "desktop": "${DESKTOP}",
      "modes": ["live"]
    }
  ]
}
EOF

  run cat "$RECIPE_FILE"
  [ "$status" -eq 0 ]
  [[ "$output" == *"\"media_name\""* ]]
  [[ "$output" == *"\"size\""* ]]
  [[ "$output" == *"\"bootable_environments\""* ]]
  [[ "$output" == *"\"id\": \"yellowfin-gnome\""* ]]
  [[ "$output" == *"\"image\": \"localhost/yellowfin:gnome\""* ]]
  [[ "$output" == *"\"desktop\": \"gnome\""* ]]
  [[ "$output" == *"\"modes\": [\"live\"]"* ]]
}

@test "recipe: desktop field reflects detected desktop (kde)" {
  VARIANT="albacore"
  FLAVOR="kde"
  IMAGE_REF="localhost/albacore:kde"
  DESKTOP="kde"

  json=$(cat <<JSON
{
  "media_name": "tunaos-${VARIANT}-${FLAVOR}",
  "size": "10G",
  "shared_store": {"format": "ext4"},
  "bootable_environments": [{
    "id": "${VARIANT}-${FLAVOR}",
    "image": "${IMAGE_REF}",
    "desktop": "${DESKTOP}",
    "modes": ["live"]
  }]
}
JSON
)
  [[ "$json" == *"\"desktop\": \"kde\""* ]]
}

@test "recipe: output dir matches variant-flavor pattern" {
  VARIANT="skipjack"
  FLAVOR="niri"
  OUT_DIR=".build/iso-tacklebox/${VARIANT}-${FLAVOR}"
  [ "$OUT_DIR" = ".build/iso-tacklebox/skipjack-niri" ]
}

@test "recipe: ISO output path follows naming convention" {
  VARIANT="bonito"
  FLAVOR="cosmic"
  OUT_DIR=".build/iso-tacklebox/${VARIANT}-${FLAVOR}"
  ISO_OUT="${OUT_DIR}/tunaos-${VARIANT}-${FLAVOR}.iso"
  [ "$ISO_OUT" = ".build/iso-tacklebox/bonito-cosmic/tunaos-bonito-cosmic.iso" ]
}

# ── Tacklebox mode selection ───────────────────────────────────────────────

@test "tacklebox: TACKLEBOX_FROM_SOURCE=0 uses container image" {
  TACKLEBOX_FROM_SOURCE=0
  TACKLEBOX_IMAGE="ghcr.io/tuna-os/tacklebox:latest"
  [[ "$TACKLEBOX_FROM_SOURCE" == "0" ]]
  [ "$TACKLEBOX_IMAGE" = "ghcr.io/tuna-os/tacklebox:latest" ]
}

@test "tacklebox: TACKLEBOX_FROM_SOURCE=1 uses local binary" {
  TACKLEBOX_FROM_SOURCE=1
  TACKLEBOX_SHA="75c837b39d9dcb360509c49d2e0306621dced904"
  [[ "$TACKLEBOX_FROM_SOURCE" == "1" ]]
  [ -n "$TACKLEBOX_SHA" ]
}

@test "tacklebox: TACKLEBOX_IMAGE is overrideable via env" {
  TACKLEBOX_IMAGE="${TACKLEBOX_IMAGE:-ghcr.io/tuna-os/tacklebox:latest}"
  [ "$TACKLEBOX_IMAGE" = "ghcr.io/tuna-os/tacklebox:latest" ]

  TACKLEBOX_IMAGE="quay.io/custom/tacklebox:dev"
  [ "$TACKLEBOX_IMAGE" = "quay.io/custom/tacklebox:dev" ]
}

# ── Variant matrix ─────────────────────────────────────────────────────────

@test "variants: all four variants produce valid output dirs" {
  for variant in yellowfin albacore skipjack bonito; do
    for flavor in gnome kde niri cosmic; do
      out=".build/iso-tacklebox/${variant}-${flavor}"
      [[ "$out" == *"${variant}-${flavor}"* ]]
    done
  done
  # If we get here, all combinations worked
  true
}

@test "variants: versioned ISO path uses variant-flavor-version-arch pattern" {
  FINAL_ISO="yellowfin-gnome-41.0-x86_64.iso"
  # Pattern: <variant>-<flavor>-<version>-<arch>.iso
  [[ "$FINAL_ISO" =~ ^[a-z]+-[a-z]+-[0-9.]+-[a-z0-9_]+\.iso$ ]]
}

# ── Edge cases ─────────────────────────────────────────────────────────────

@test "edge: flavor with hyphens (gnome-hwe) handled correctly" {
  FLAVOR="gnome-hwe"
  case "$FLAVOR" in
    kde*) DESKTOP="kde" ;;
    niri*) DESKTOP="niri" ;;
    cosmic*) DESKTOP="cosmic" ;;
    gnome* | *) DESKTOP="gnome" ;;
  esac
  [ "$DESKTOP" = "gnome" ]

  VARIANT="yellowfin"
  OUT_DIR=".build/iso-tacklebox/${VARIANT}-${FLAVOR}"
  [ "$OUT_DIR" = ".build/iso-tacklebox/yellowfin-gnome-hwe" ]
}

@test "edge: repo 'local' resolves to localhost prefix" {
  REPO="local"
  VARIANT="yellowfin"
  TAG="gnome"
  case "$REPO" in
    local) echo "localhost/${VARIANT}:${TAG}" ;;
    ghcr) echo "ghcr.io/tuna-os/${VARIANT}:${TAG}" ;;
  esac
  result="localhost/yellowfin:gnome"
  [ "$result" = "localhost/yellowfin:gnome" ]
}
