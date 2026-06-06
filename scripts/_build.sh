#!/usr/bin/env bash
# _build.sh — Core 3-pass build engine (podman build → chunkah rechunk → podman label).
# Extracted from just/build.just (RFC-006 Phase 3).
#
# Required env vars (set by calling just recipe):
#   YQ, COMMON_IMAGE, BREW_IMAGE, REPO_ORGANIZATION, COREOS_STABLE_VERSION, JUST
#
# Positional args (9 + rest):
#   $1: target_tag_with_version
#   $2: target_tag
#   $3: container_file
#   $4: base_image_for_build
#   $5: target_platform
#   $6: use_cache
#   $7: enable_nvidia
#   $8: enable_hwe
#   $9: desktop_flavor
#   ${10}: hw_variant
#   ${11}...: extra podman build args (*args from just)
set -euxo pipefail

target_tag_with_version="$1"
target_tag="$2"
container_file="$3"
base_image_for_build="$4"
target_platform="$5"
use_cache="$6"
enable_nvidia="$7"
enable_hwe="$8"
desktop_flavor="$9"
hw_variant="${10}"
shift 10
extra_args=("$@")

# ── Image digests ────────────────────────────────────────────────────────────
common_image_sha=$("${YQ}" -r '.images[] | select(.name == "common") | .digest' image-versions.yaml)
common_image_ref="${COMMON_IMAGE}@${common_image_sha}"
brew_image_sha=$("${YQ}" -r '.images[] | select(.name == "brew") | .digest' image-versions.yaml)
brew_image_ref="${BREW_IMAGE}@${brew_image_sha}"

# ── Build args ───────────────────────────────────────────────────────────────
BUILD_ARGS=()
BUILD_ARGS+=("--build-arg" "IMAGE_NAME=${target_tag}")
BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR=${REPO_ORGANIZATION}")
BUILD_ARGS+=("--build-arg" "BASE_IMAGE=${base_image_for_build}")
BUILD_ARGS+=("--build-arg" "COMMON_IMAGE_REF=${common_image_ref}")
BUILD_ARGS+=("--build-arg" "BREW_IMAGE_REF=${brew_image_ref}")
BUILD_ARGS+=("--build-arg" "ENABLE_HWE=${enable_hwe}")
BUILD_ARGS+=("--build-arg" "ENABLE_NVIDIA=${enable_nvidia}")
BUILD_ARGS+=("--build-arg" "HW_VARIANT=${hw_variant}")
BUILD_ARGS+=("--build-arg" "DESKTOP_FLAVOR=${desktop_flavor}")

AKMODS_ORG=$("${YQ}" -r ".variants[] | select(.id == \"${target_tag}\") | .akmods // \"ublue-os\"" .github/build-config.yml)
BUILD_ARGS+=("--build-arg" "AKMODS_BASE=ghcr.io/${AKMODS_ORG}")

# ── RHSM credentials (BuildKit secret) ───────────────────────────────────────
RHSM_SECRET_FILE=""
if [[ -n "${RHSM_USER:-}${RHSM_PASSWORD:-}${RHSM_ORG:-}${RHSM_ACTIVATION_KEY:-}" ]]; then
    RHSM_SECRET_FILE=$(mktemp)
    # shellcheck disable=SC2064
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

# ── Akmods version ────────────────────────────────────────────────────────────
if [[ "${enable_hwe}" -eq "1" ]] || [[ "${target_tag}" == bonito* ]]; then
    BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=coreos-stable-${COREOS_STABLE_VERSION}")
    BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=coreos-stable-${COREOS_STABLE_VERSION}")
else
    BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=centos-10")
    BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=centos-10")
fi
BUILD_ARGS+=("--build-arg" "IMAGE_NAME_VARIANT=${target_tag}")

# ── Upstream snapshot SHAs ───────────────────────────────────────────────────
UPSTREAM_JSON="{}"
SNAPSHOTS_DIR="_upstream-snapshots"
if [[ -d "${SNAPSHOTS_DIR}" ]]; then
    declare -a snapshot_entries=()
    for snap_dir in "${SNAPSHOTS_DIR}"/*/; do
        [[ -d "${snap_dir}" ]] || continue
        name=$(basename "${snap_dir}")
        [[ -f "${snap_dir}.snapshot.json" ]] || continue
        sha=$(jq -r '.sha' "${snap_dir}.snapshot.json" 2>/dev/null)
        [[ -n "${sha}" && "${sha}" != "null" ]] || continue
        snapshot_entries+=("\"${name}\":\"${sha}\"")
    done
    if [[ ${#snapshot_entries[@]} -gt 0 ]]; then
        UPSTREAM_JSON="{$(IFS=','; echo "${snapshot_entries[*]}")}"
    fi
fi
BUILD_ARGS+=("--build-arg" "UPSTREAM_SNAPSHOTS=${UPSTREAM_JSON}")

# ── Git SHA ──────────────────────────────────────────────────────────────────
if [[ -z "$(git status -s)" ]]; then
    BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=$(git rev-parse --short HEAD)")
else
    BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=dirty")
fi

# ── Build cache ──────────────────────────────────────────────────────────────
if [[ "${use_cache}" == "1" ]]; then
    readarray -t CACHE_MOUNTS < <(./scripts/setup-build-cache.sh "${target_tag}")
    BUILD_ARGS+=("${CACHE_MOUNTS[@]}")
fi

DESKTOP_FLAVOR="${desktop_flavor}"
PRE_CHUNK_TAG="${target_tag_with_version}-pre-chunk"

# ══════════════════════════════════════════════════════════════════════════════
# Pass 1: Build the target DE stage directly — no unused stages built
# ══════════════════════════════════════════════════════════════════════════════
echo "==> Building ${DESKTOP_FLAVOR} stage..."

podman build \
    --security-opt label=disable \
    --dns=8.8.8.8 \
    --platform "${target_platform}" \
    --target="${DESKTOP_FLAVOR}" \
    "${BUILD_ARGS[@]}" \
    --tag "${PRE_CHUNK_TAG}" \
    "${extra_args[@]}" \
    --pull=newer \
    --file "${container_file}" \
    .

# ══════════════════════════════════════════════════════════════════════════════
# Pass 2: Run chunkah externally against the built image
# ══════════════════════════════════════════════════════════════════════════════
echo "==> Running chunkah on ${PRE_CHUNK_TAG}..."

CHUNKAH_IMAGE="quay.io/coreos/chunkah:latest"
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
    --dns=8.8.8.8 \
    --entrypoint="" \
    -v "${CHUNK_OUT}:/run/out:Z" \
    --mount "type=image,source=${PRE_CHUNK_TAG},target=/chunkah" \
    "${CHUNKAH_IMAGE}" \
    sh -c 'chunkah build > /run/out/out.ociarchive'
mv "${CHUNK_OUT}/out.ociarchive" out.ociarchive
rm -rf "${CHUNK_OUT}"

# ══════════════════════════════════════════════════════════════════════════════
# Pass 3: Load archive into podman storage, apply OCI labels
# ══════════════════════════════════════════════════════════════════════════════
echo "==> Applying labels from OCI archive..."

podman system prune -af 2>/dev/null || true

RECHUNKED_REF="localhost/${target_tag_with_version}-rechunked-$$"
LOADED_ID=$(podman load --input out.ociarchive | awk '/Loaded image/{print $NF}')
rm -f out.ociarchive
if [[ -z "${LOADED_ID}" ]]; then
    echo "ERROR: podman load produced no image ID; the OCI archive may be corrupt or disk full" >&2
    exit 1
fi
podman tag "${LOADED_ID}" "${RECHUNKED_REF}"

podman build \
    --security-opt label=disable \
    --dns=8.8.8.8 \
    "${BUILD_ARGS[@]}" \
    --build-arg "RECHUNKED_BASE=${RECHUNKED_REF}" \
    --tag "${target_tag_with_version}" \
    --file "Containerfile.final" \
    .

podman rmi "${RECHUNKED_REF}" 2>/dev/null || true
