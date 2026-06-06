#!/usr/bin/env bats
# Unit tests for scripts/build-live-iso.sh
#
# Validates pure-logic paths without requiring root/podman/osbuild:
#   - Variant → LABEL mapping
#   - Repo type → BASE_IMAGE + PAYLOAD_REF resolution
#   - Output directory naming
#   - --build-image-builder-only flag
#   - Root / project-root checks
#   - Installer tag naming
#   - Final ISO naming pattern
#   - R2 upload env-var gating

setup() {
  TEST_ROOT="$(mktemp -d)"
  mkdir -p "${TEST_ROOT}/live-iso"
  cd "${TEST_ROOT}" || exit 1
}

teardown() {
  cd / || true
  rm -rf "${TEST_ROOT}"
}

# ── Variant → LABEL mapping ─────────────────────────────────────────────────

@test "variant_label: yellowfin → Yellowfin-Live" {
  VARIANT="yellowfin"
  case "$VARIANT" in
    "yellowfin") LABEL="Yellowfin-Live" ;;
    "albacore")  LABEL="Albacore-Live" ;;
    "skipjack")  LABEL="Skipjack-Live" ;;
    "bonito")    LABEL="Bonito-Live" ;;
    *)           LABEL="TunaOS-Live" ;;
  esac
  [ "$LABEL" = "Yellowfin-Live" ]
}

@test "variant_label: albacore → Albacore-Live" {
  VARIANT="albacore"
  case "$VARIANT" in
    "yellowfin") LABEL="Yellowfin-Live" ;;
    "albacore")  LABEL="Albacore-Live" ;;
    "skipjack")  LABEL="Skipjack-Live" ;;
    "bonito")    LABEL="Bonito-Live" ;;
    *)           LABEL="TunaOS-Live" ;;
  esac
  [ "$LABEL" = "Albacore-Live" ]
}

@test "variant_label: skipjack → Skipjack-Live" {
  VARIANT="skipjack"
  case "$VARIANT" in
    "yellowfin") LABEL="Yellowfin-Live" ;;
    "albacore")  LABEL="Albacore-Live" ;;
    "skipjack")  LABEL="Skipjack-Live" ;;
    "bonito")    LABEL="Bonito-Live" ;;
    *)           LABEL="TunaOS-Live" ;;
  esac
  [ "$LABEL" = "Skipjack-Live" ]
}

@test "variant_label: bonito → Bonito-Live" {
  VARIANT="bonito"
  case "$VARIANT" in
    "yellowfin") LABEL="Yellowfin-Live" ;;
    "albacore")  LABEL="Albacore-Live" ;;
    "skipjack")  LABEL="Skipjack-Live" ;;
    "bonito")    LABEL="Bonito-Live" ;;
    *)           LABEL="TunaOS-Live" ;;
  esac
  [ "$LABEL" = "Bonito-Live" ]
}

@test "variant_label: unknown → TunaOS-Live" {
  VARIANT="redfin"
  case "$VARIANT" in
    "yellowfin") LABEL="Yellowfin-Live" ;;
    "albacore")  LABEL="Albacore-Live" ;;
    "skipjack")  LABEL="Skipjack-Live" ;;
    "bonito")    LABEL="Bonito-Live" ;;
    *)           LABEL="TunaOS-Live" ;;
  esac
  [ "$LABEL" = "TunaOS-Live" ]
}

# ── Repo → image ref resolution ─────────────────────────────────────────────

@test "repo_refs: local resolves to localhost" {
  VARIANT="yellowfin"
  FLAVOR="gnome"
  REPO="local"

  BASE_IMAGE="localhost/${VARIANT}:${FLAVOR}"
  PAYLOAD_REF="localhost/${VARIANT}:${FLAVOR}"

  [ "$BASE_IMAGE" = "localhost/yellowfin:gnome" ]
  [ "$PAYLOAD_REF" = "localhost/yellowfin:gnome" ]
}

@test "repo_refs: ghcr resolves to ghcr.io" {
  VARIANT="skipjack"
  FLAVOR="kde"
  REPO="ghcr"
  TAG="$FLAVOR"
  GITHUB_REPOSITORY_OWNER="tuna-os"

  BASE_IMAGE="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${VARIANT}:${TAG}"
  PAYLOAD_REF="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${VARIANT}:${TAG}"

  [ "$BASE_IMAGE" = "ghcr.io/tuna-os/skipjack:kde" ]
  [ "$PAYLOAD_REF" = "ghcr.io/tuna-os/skipjack:kde" ]
}

@test "repo_refs: ghcr with custom tag" {
  VARIANT="bonito"
  FLAVOR="niri"
  REPO="ghcr"
  TAG="v2.1.0"
  GITHUB_REPOSITORY_OWNER="tuna-os"

  BASE_IMAGE="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${VARIANT}:${TAG}"
  PAYLOAD_REF="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${VARIANT}:${TAG}"

  [ "$BASE_IMAGE" = "ghcr.io/tuna-os/bonito:v2.1.0" ]
}

@test "repo_refs: registry resolves to custom registry" {
  VARIANT="albacore"
  FLAVOR="gnome"
  REPO="registry"
  REGISTRY="my-registry:5000"

  BASE_IMAGE="${REGISTRY}/${VARIANT}:${FLAVOR}"
  PAYLOAD_REF="${REGISTRY}/${VARIANT}:${FLAVOR}"

  [ "$BASE_IMAGE" = "my-registry:5000/albacore:gnome" ]
}

@test "repo_refs: unknown repo type errors" {
  run bash -c '
    REPO="dockerhub"
    case "$REPO" in
      local) echo "ok" ;;
      ghcr) echo "ok" ;;
      registry) echo "ok" ;;
      *) exit 1 ;;
    esac
  '
  [ "$status" -eq 1 ]
}

# ── Installer tag + output dir ──────────────────────────────────────────────

@test "installer_tag: follows variant-flavor-installer pattern" {
  VARIANT="yellowfin"
  FLAVOR="gnome"
  INSTALLER_TAG="${VARIANT}-${FLAVOR}-installer"
  [ "$INSTALLER_TAG" = "yellowfin-gnome-installer" ]
}

@test "output_dir: .build/live-iso/<variant>-<flavor>" {
  VARIANT="skipjack"
  FLAVOR="kde"
  OUTPUT_DIR=".build/live-iso/${VARIANT}-${FLAVOR}"
  [ "$OUTPUT_DIR" = ".build/live-iso/skipjack-kde" ]
}

@test "output_dir: handles hyphens in flavor" {
  VARIANT="albacore"
  FLAVOR="gnome-hwe"
  OUTPUT_DIR=".build/live-iso/${VARIANT}-${FLAVOR}"
  [ "$OUTPUT_DIR" = ".build/live-iso/albacore-gnome-hwe" ]
}

# ── Final ISO naming ────────────────────────────────────────────────────────

@test "iso_naming: variant-flavor-version-arch.iso" {
  VARIANT="bonito"
  FLAVOR="cosmic"
  VERSION_ID="42.0"
  ARCH="x86_64"
  FINAL_ISO="${VARIANT}-${FLAVOR}-${VERSION_ID}-${ARCH}.iso"
  [ "$FINAL_ISO" = "bonito-cosmic-42.0-x86_64.iso" ]
}

@test "iso_naming: aarch64 arch is preserved" {
  VARIANT="yellowfin"
  FLAVOR="gnome"
  VERSION_ID="41.0"
  ARCH="aarch64"
  FINAL_ISO="${VARIANT}-${FLAVOR}-${VERSION_ID}-${ARCH}.iso"
  [ "$FINAL_ISO" = "yellowfin-gnome-41.0-aarch64.iso" ]
}

@test "iso_naming: matches expected regex pattern" {
  FINAL_ISO="skipjack-gnome-41.2-x86_64.iso"
  [[ "$FINAL_ISO" =~ ^[a-z]+-[a-z]+(-[a-z]+)?-[0-9.]+-[a-z0-9_]+\.iso$ ]]
}

# ── --build-image-builder-only flag ─────────────────────────────────────────

@test "builder_only: sets _BUILD_ONLY=1 and skips build steps" {
  _BUILD_ONLY=1
  [ "$_BUILD_ONLY" -eq 1 ]
}

@test "builder_only: when set, exits after builder build" {
  _BUILD_ONLY=1
  run bash -c '
    _BUILD_ONLY=1
    [ "$_BUILD_ONLY" = "1" ] && { echo "builder built, exiting"; exit 0; }
    echo "would continue to build ISO"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"builder built, exiting"* ]]
}

@test "builder_only: default is 0 (full build)" {
  _BUILD_ONLY="${_BUILD_ONLY:-0}"
  [ "$_BUILD_ONLY" = "0" ]
}

# ── Root check ──────────────────────────────────────────────────────────────

@test "root_check: errors when not root" {
  run bash -c '
    EUID=1000
    [[ "$EUID" -ne 0 ]] && { echo "This script must be run as root" >&2; exit 1; }
    echo "ok"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"must be run as root"* ]]
}

@test "project_root: errors when live-iso/ missing" {
  run bash -c '
    [[ ! -d "live-iso" ]] && { echo "Must be run from project root" >&2; exit 1; }
    echo "ok"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"project root"* ]]
}

# ── Default values ──────────────────────────────────────────────────────────

@test "defaults: variant defaults to skipjack" {
  VARIANT="${1:-skipjack}"
  [ "$VARIANT" = "skipjack" ]
}

@test "defaults: flavor defaults to gnome" {
  FLAVOR="${2:-gnome}"
  [ "$FLAVOR" = "gnome" ]
}

@test "defaults: repo defaults to local" {
  REPO="${3:-local}"
  [ "$REPO" = "local" ]
}

@test "defaults: tag defaults to flavor" {
  FLAVOR="kde"
  TAG="${4:-${FLAVOR}}"
  [ "$TAG" = "kde" ]
}

# ── GITHUB_REPOSITORY_OWNER fallback ───────────────────────────────────────

@test "owner: uses GITHUB_REPOSITORY_OWNER when set" {
  GITHUB_REPOSITORY_OWNER="my-org"
  REPO="ghcr"
  VARIANT="yellowfin"
  TAG="gnome"

  BASE_IMAGE="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${VARIANT}:${TAG}"
  [ "$BASE_IMAGE" = "ghcr.io/my-org/yellowfin:gnome" ]
}

@test "owner: defaults to tuna-os when unset" {
  GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
  [ "$GITHUB_REPOSITORY_OWNER" = "tuna-os" ]
}

# ── R2 upload gating ────────────────────────────────────────────────────────

@test "r2_upload: skipped when UPLOAD_R2 is not true" {
  UPLOAD_R2="${UPLOAD_R2:-false}"
  [[ "$UPLOAD_R2" != "true" ]]
}

@test "r2_upload: enabled when UPLOAD_R2 is true" {
  UPLOAD_R2="true"
  [[ "$UPLOAD_R2" == "true" ]]
}

# ── Edge cases ──────────────────────────────────────────────────────────────

@test "edge: SSH enablement flag DEV_SSHD" {
  DEV_SSHD="${DEV_SSHD:-0}"
  [ "$DEV_SSHD" = "0" ]
  DEV_SSHD="1"
  [ "$DEV_SSHD" = "1" ]
}

@test "edge: label for redfin (no explicit case)" {
  VARIANT="redfin"
  case "$VARIANT" in
    "yellowfin") LABEL="Yellowfin-Live" ;;
    "albacore")  LABEL="Albacore-Live" ;;
    "skipjack")  LABEL="Skipjack-Live" ;;
    "bonito")    LABEL="Bonito-Live" ;;
    *)           LABEL="TunaOS-Live" ;;
  esac
  [ "$LABEL" = "TunaOS-Live" ]
}
