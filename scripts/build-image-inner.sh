#!/usr/bin/env bash
# build-image-inner.sh — The container image build engine.
#
# Replaces the Justfile _build recipe. Driven by environment variables
# (not positional args) for readability and testability.
#
# Required env vars:
#   IMAGE_TAG          — full tag (e.g. "yellowfin:gnome")
#   VARIANT            — variant name (e.g. "yellowfin")
#   CONTAINERFILE      — which Containerfile to use
#   BASE_IMAGE         — the FROM image for the build
#   PLATFORM           — target platform(s) (e.g. "linux/amd64")
#   DESKTOP_FLAVOR     — the --target stage name
#   ENABLE_HWE         — 0 or 1
#   ENABLE_NVIDIA      — 0 or 1
#   ENABLE_SSHD        — 0 or 1
#
# Optional env vars:
#   OVERLAY_TYPE       — hwe or nvidia (for Containerfile.overlay)
#   USE_CACHE          — 1 to enable local dnf cache mounts
#   IS_CI              — 1 if running in CI
#   SKIP_RECHUNK       — 1 to skip chunkah passes (PR builds)
#   IMAGE_REGISTRY     — defaults to ghcr.io
#   REPO_ORGANIZATION  — defaults to tuna-os
#   CHUNKAH_IMAGE      — override chunkah image ref
#   BUILDAH_CACHE_FLAGS — extra flags for buildah layer cache

set -euxo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io}"
REPO_ORGANIZATION="${REPO_ORGANIZATION:-tuna-os}"
IS_CI="${IS_CI:-0}"
USE_CACHE="${USE_CACHE:-0}"
SKIP_RECHUNK="${SKIP_RECHUNK:-0}"
ENABLE_SSHD="${ENABLE_SSHD:-0}"
YQ="${YQ:-yq}"

# ── Source shared helpers ─────────────────────────────────────────────────────
source scripts/_registry.sh

# ── Resolve image refs from image-versions.yaml ───────────────────────────────
common_image="${COMMON_IMAGE:-ghcr.io/projectbluefin/common}"
brew_image="${BREW_IMAGE:-ghcr.io/ublue-os/brew}"

common_image_sha=$($YQ -r '.images[] | select(.name == "common") | .digest' image-versions.yaml)
common_image_ref="${common_image}@${common_image_sha}"
brew_image_sha=$($YQ -r '.images[] | select(.name == "brew") | .digest' image-versions.yaml)
brew_image_ref="${brew_image}@${brew_image_sha}"
zirconium_image_sha=$($YQ -r '.images[] | select(.name == "zirconium") | .digest' image-versions.yaml)

# ── Build args ────────────────────────────────────────────────────────────────
BUILD_ARGS=()
BUILD_ARGS+=("--build-arg" "IMAGE_NAME=${VARIANT}")
BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR=${REPO_ORGANIZATION}")
BUILD_ARGS+=("--build-arg" "IMAGE_REGISTRY=${IMAGE_REGISTRY}")
BUILD_ARGS+=("--build-arg" "BASE_IMAGE=${BASE_IMAGE}")
BUILD_ARGS+=("--build-arg" "COMMON_IMAGE_REF=${common_image_ref}")
BUILD_ARGS+=("--build-arg" "BREW_IMAGE_REF=${brew_image_ref}")
BUILD_ARGS+=("--build-arg" "ENABLE_HWE=${ENABLE_HWE}")
BUILD_ARGS+=("--build-arg" "ENABLE_NVIDIA=${ENABLE_NVIDIA}")
BUILD_ARGS+=("--build-arg" "DESKTOP_FLAVOR=${DESKTOP_FLAVOR}")
BUILD_ARGS+=("--build-arg" "ENABLE_SSHD=${ENABLE_SSHD}")
BUILD_ARGS+=("--build-arg" "IMAGE_NAME_VARIANT=${VARIANT}")
BUILD_ARGS+=("--build-arg" "ZIRCONIUM_IMAGE_REF=ghcr.io/zirconium-dev/zirconium@${zirconium_image_sha}")

# Overlay type for Containerfile.overlay
if [[ -n "${OVERLAY_TYPE:-}" ]]; then
    BUILD_ARGS+=("--build-arg" "OVERLAY_TYPE=${OVERLAY_TYPE}")
fi

# Akmods version selection
AKMODS_ORG=$($YQ -r ".variants[] | select(.id == \"${VARIANT}\") | .akmods // \"ublue-os\"" .github/build-config.yml)
AKMODS_REGISTRY_BASE="$(registry_ref akmods 2>/dev/null || echo "ghcr.io/${AKMODS_ORG}")"
BUILD_ARGS+=("--build-arg" "AKMODS_BASE=${AKMODS_REGISTRY_BASE}")

if [[ "${ENABLE_HWE}" == "1" ]] || [[ "${VARIANT}" == bonito* ]]; then
    COREOS_STABLE="${COREOS_STABLE_VERSION:-41}"
    BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=coreos-stable-${COREOS_STABLE}")
    BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=coreos-stable-${COREOS_STABLE}")
else
    BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=centos-10")
    BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=centos-10")
fi

# RHSM secret (RHEL only)
RHSM_SECRET_FILE=""
if [[ -n "${RHSM_USER:-}${RHSM_PASSWORD:-}${RHSM_ORG:-}${RHSM_ACTIVATION_KEY:-}" ]]; then
    RHSM_SECRET_FILE=$(mktemp)
    # shellcheck disable=SC2064 # intentional: capture path at definition time
    trap "rm -f '${RHSM_SECRET_FILE}'" EXIT
    chmod 0600 "${RHSM_SECRET_FILE}"
    {
        printf 'export RHSM_USER=%q\n'           "${RHSM_USER:-}"
        printf 'export RHSM_PASSWORD=%q\n'       "${RHSM_PASSWORD:-}"
        printf 'export RHSM_ORG=%q\n'            "${RHSM_ORG:-}"
        printf 'export RHSM_ACTIVATION_KEY=%q\n' "${RHSM_ACTIVATION_KEY:-}"
    } > "${RHSM_SECRET_FILE}"
    BUILD_ARGS+=("--secret" "id=rhsm,src=${RHSM_SECRET_FILE}")
fi

# Build scripts hash for cache invalidation
build_scripts_hash=$(find build_scripts -type f -name '*.sh' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
BUILD_ARGS+=("--build-arg" "BUILD_SCRIPTS_HASH=${build_scripts_hash}")

# Git SHA
if [[ -z "$(git status -s)" ]]; then
    BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=$(git rev-parse --short HEAD)")
else
    BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=dirty")
fi

# Local cache mounts
if [[ "${USE_CACHE}" == "1" ]]; then
    readarray -t CACHE_MOUNTS < <(./scripts/setup-build-cache.sh "${VARIANT}")
    BUILD_ARGS+=("${CACHE_MOUNTS[@]}")
fi

# ── Pass 1: Build image ──────────────────────────────────────────────────────
PRE_CHUNK_TAG="${IMAGE_TAG}-pre-chunk"

BUILDER="podman"
PULL_FLAG="--pull=newer"
if [[ "${IS_CI}" == "1" ]] && command -v buildah &>/dev/null; then
    BUILDER="buildah"
    PULL_FLAG="--pull-always"
fi

echo "==> Building ${DESKTOP_FLAVOR} stage..."

${BUILDER} build \
    --security-opt label=disable \
    --dns=8.8.8.8 \
    --platform "${PLATFORM}" \
    --target="${DESKTOP_FLAVOR}" \
    "${BUILD_ARGS[@]}" \
    --tag "${PRE_CHUNK_TAG}" \
    ${PULL_FLAG} \
    --file "${CONTAINERFILE}" \
    ${BUILDAH_CACHE_FLAGS:-} \
    .

# ── Skip rechunk for PR builds ───────────────────────────────────────────────
if [[ "${SKIP_RECHUNK}" == "1" ]]; then
    echo "==> SKIP_RECHUNK=1 — tagging pre-chunk image as final"
    ${BUILDER} tag "${PRE_CHUNK_TAG}" "${IMAGE_TAG}"
    exit 0
fi

# ── Pass 2: Rechunk ──────────────────────────────────────────────────────────
echo "==> Running chunkah on ${PRE_CHUNK_TAG}..."

if [[ -z "${CHUNKAH_IMAGE:-}" ]]; then
    CHUNKAH_IMAGE="quay.io/coreos/chunkah:latest"
fi
if ! podman image inspect "${CHUNKAH_IMAGE}" &>/dev/null; then
    if ! podman pull "${CHUNKAH_IMAGE}" 2>/dev/null; then
        echo "==> chunkah image not pullable, building from source..."
        ./scripts/build-chunkah.sh
        CHUNKAH_IMAGE="localhost/chunkah:latest"
    fi
fi

CHUNK_OUT=$(mktemp -d)
podman run --rm \
    --security-opt label=disable \
    --network host \
    --entrypoint="" \
    -v "${CHUNK_OUT}:/run/out:Z" \
    --mount "type=image,source=${PRE_CHUNK_TAG},target=/chunkah" \
    "${CHUNKAH_IMAGE}" \
    sh -c 'chunkah build > /run/out/out.ociarchive'
mv "${CHUNK_OUT}/out.ociarchive" out.ociarchive
rm -rf "${CHUNK_OUT}"

# ── Pass 3: Relabel ──────────────────────────────────────────────────────────
echo "==> Applying labels from OCI archive..."

podman system prune -af 2>/dev/null || true

RECHUNKED_REF="localhost/${IMAGE_TAG}-rechunked-$$"
LOADED_ID=$(TMPDIR=${TMPDIR:-/tmp} podman load --input out.ociarchive | awk '/Loaded image/{print $NF}')
rm -f out.ociarchive
if [[ -z "${LOADED_ID}" ]]; then
    echo "ERROR: podman load produced no image ID" >&2
    exit 1
fi
podman tag "${LOADED_ID}" "${RECHUNKED_REF}"

${BUILDER} build \
    --security-opt label=disable \
    --dns=8.8.8.8 \
    "${BUILD_ARGS[@]}" \
    --build-arg "RECHUNKED_BASE=${RECHUNKED_REF}" \
    --tag "${IMAGE_TAG}" \
    --file "Containerfile.final" \
    .

${BUILDER} rmi "${RECHUNKED_REF}" 2>/dev/null || true
