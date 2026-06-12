#!/usr/bin/env bash
# Build a TunaOS image (variant + flavor).
# Combines the logic of the Justfile 'build' and '_build' recipes.
#
# Usage: scripts/build-image.sh <variant> [flavor] [platform] [is_ci] [tag] [chain_base_image]

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Source registry abstraction for configurable mirror support (RFC-009)
source scripts/_registry.sh

VARIANT="${1:-albacore}"
FLAVOR="${2:-gnome}"
TARGET_PLATFORM="${3:-}"
IS_CI="${4:-0}"
TAG="${5:-latest}"
CHAIN_BASE_IMAGE="${6:-}"

YQ="${yq:-$(command -v yq 2>/dev/null || echo /home/linuxbrew/.linuxbrew/bin/yq)}"

# ── Build setup (from 'build' recipe) ──────────────────────────────────────

DID_INIT="0"
if [[ "$IS_CI" != "1" ]] && [[ "${SKIP_SUBMODULES:-0}" != "1" ]]; then
	if [[ "$FLAVOR" == *"gnome"* ]]; then
		git submodule update --init --recursive
		DID_INIT="1"
	fi
fi

if [[ -z "$TARGET_PLATFORM" ]]; then
	if [[ "$IS_CI" != "1" ]]; then
		if [[ -n "${platform:-}" ]]; then
			PLATFORM="${platform}"
		else
			ARCH=$(uname -m)
			if [[ "$ARCH" == "x86_64" ]]; then
				if rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; then
					PLATFORM="linux/amd64/v2"
				else
					PLATFORM="linux/amd64"
				fi
			elif [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" ]]; then
				PLATFORM="linux/arm64"
			else
				echo "Unsupported ARCH '$ARCH'." >&2
				exit 1
			fi
		fi
	else
		PLATFORM=$("$YQ" -r ".variants[] | select(.id == \"$VARIANT\") | .platforms | join(\",\")" .github/build-config.yml)
	fi
else
	PLATFORM="$TARGET_PLATFORM"
fi

BASE_FOR_BUILD=""
CONTAINERFILE="Containerfile"
ENABLE_HWE="0"
ENABLE_NVIDIA="0"
PARENT_FLAVOR=""
DESKTOP_FLAVOR="$FLAVOR"

case "$FLAVOR" in
"hwe") FLAVOR="gnome-hwe" ;;
"nvidia") FLAVOR="gnome-nvidia" ;;
"nvidia-hwe") FLAVOR="gnome-nvidia-hwe" ;;
esac

if [[ "$FLAVOR" == "all" ]]; then
	readarray -t FLAVORS < <("$YQ" -r ".variants[] | select(.id == \"$VARIANT\") | .flavors[].id" .github/build-config.yml)
	for f in "${FLAVORS[@]}"; do
		just build "$VARIANT" "$f"
	done
	exit 0
elif [[ "$FLAVOR" == "base" ]]; then
	BASE_FOR_BUILD=$(./scripts/get-base-image.sh "$VARIANT")
	DESKTOP_FLAVOR="base-no-de"
elif [[ "$FLAVOR" == "base-hwe" ]]; then
	CONTAINERFILE="Containerfile.hwe"
	ENABLE_HWE="1"
	DESKTOP_FLAVOR="base-hwe"
	PARENT_FLAVOR="base"
elif [[ "$FLAVOR" == "base-nvidia" ]]; then
	CONTAINERFILE="Containerfile.nvidia"
	ENABLE_NVIDIA="1"
	DESKTOP_FLAVOR="base-nvidia"
	PARENT_FLAVOR="base"
elif [[ "$FLAVOR" == *"-nvidia-hwe" ]]; then
	DESKTOP_FLAVOR="${FLAVOR%-nvidia-hwe}"
	CONTAINERFILE="Containerfile.nvidia"
	ENABLE_NVIDIA="1"
	ENABLE_HWE="1"
	PARENT_FLAVOR="${DESKTOP_FLAVOR}-hwe"
elif [[ "$FLAVOR" == *"-hwe" ]]; then
	DESKTOP_FLAVOR="${FLAVOR%-hwe}"
	CONTAINERFILE="Containerfile.hwe"
	ENABLE_HWE="1"
	PARENT_FLAVOR="${DESKTOP_FLAVOR}"
elif [[ "$FLAVOR" == *"-nvidia" ]]; then
	DESKTOP_FLAVOR="${FLAVOR%-nvidia}"
	CONTAINERFILE="Containerfile.nvidia"
	ENABLE_NVIDIA="1"
	PARENT_FLAVOR="${DESKTOP_FLAVOR}"
else
	DESKTOP_FLAVOR="$FLAVOR"
	BASE_FOR_BUILD=$(./scripts/get-base-image.sh "$VARIANT")
fi

if [[ -n "$PARENT_FLAVOR" ]]; then
	if [[ "$IS_CI" = "1" ]]; then
		BASE_FOR_BUILD="ghcr.io/${repo_organization:-tuna-os}/${VARIANT}:${PARENT_FLAVOR}"
	else
		BASE_FOR_BUILD="localhost/${VARIANT}:${PARENT_FLAVOR}"
	fi
fi

if [[ -n "$CHAIN_BASE_IMAGE" ]] && [[ "$FLAVOR" != "base" ]]; then
	BASE_FOR_BUILD="$CHAIN_BASE_IMAGE"
fi

TARGET_TAG="$VARIANT"
TARGET_IMAGE_TAG="$TAG"
[[ "$TAG" == "latest" ]] && TARGET_IMAGE_TAG="$FLAVOR"
TARGET_TAG_WITH_VERSION="${TARGET_TAG}:${TARGET_IMAGE_TAG}"

if [[ "$IS_CI" == "0" ]]; then
	USE_CACHE="1"
else
	USE_CACHE="0"
fi

# ── Build engine (from '_build' recipe) ────────────────────────────────────

set -euxo pipefail

common_image_sha=$("$YQ" -r '.images[] | select(.name == "common") | .digest' image-versions.yaml)
common_image_ref="${common_image:-$(registry_ref common "@${common_image_sha}")}"
brew_image_sha=$("$YQ" -r '.images[] | select(.name == "brew") | .digest' image-versions.yaml)
brew_image_ref="${brew_image:-$(registry_ref brew "@${brew_image_sha}")}"

BUILD_ARGS=()
BUILD_ARGS+=("--build-arg" "IMAGE_NAME=${TARGET_TAG}")
BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR=${repo_organization:-tuna-os}")
BUILD_ARGS+=("--build-arg" "IMAGE_REGISTRY=${IMAGE_REGISTRY:-ghcr.io}")
BUILD_ARGS+=("--build-arg" "BASE_IMAGE=${BASE_FOR_BUILD}")
BUILD_ARGS+=("--build-arg" "COMMON_IMAGE_REF=${common_image_ref}")
BUILD_ARGS+=("--build-arg" "BREW_IMAGE_REF=${brew_image_ref}")
BUILD_ARGS+=("--build-arg" "ENABLE_HWE=${ENABLE_HWE}")
BUILD_ARGS+=("--build-arg" "ENABLE_NVIDIA=${ENABLE_NVIDIA}")
BUILD_ARGS+=("--build-arg" "DESKTOP_FLAVOR=${DESKTOP_FLAVOR}")

AKMODS_ORG=$("$YQ" -r ".variants[] | select(.id == \"${TARGET_TAG}\") | .akmods // \"ublue-os\"" .github/build-config.yml)
# Resolve akmods registry via registry-map; falls back to ghcr.io/${AKMODS_ORG} if not mapped
AKMODS_REGISTRY_BASE="$(registry_ref akmods 2>/dev/null || echo "ghcr.io/${AKMODS_ORG}")"
BUILD_ARGS+=("--build-arg" "AKMODS_BASE=${AKMODS_REGISTRY_BASE}")

# RHSM credentials via BuildKit-style secret (matches Justfile approach).
# Using --secret avoids leaking creds into podman history --no-trunc.
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

if [[ "$ENABLE_HWE" -eq "1" ]] || [[ "$TARGET_TAG" == bonito* ]]; then
	BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=coreos-stable-${coreos_stable_version:-43}")
	BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=coreos-stable-${coreos_stable_version:-43}")
else
	BUILD_ARGS+=("--build-arg" "AKMODS_VERSION=centos-10")
	BUILD_ARGS+=("--build-arg" "AKMODS_NVIDIA_VERSION=centos-10")
fi
BUILD_ARGS+=("--build-arg" "IMAGE_NAME_VARIANT=${TARGET_TAG}")

if [[ -z "$(git status -s)" ]]; then
	BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=$(git rev-parse --short HEAD)")
else
	BUILD_ARGS+=("--build-arg" "SHA_HEAD_SHORT=dirty")
fi

if [[ "$USE_CACHE" == "1" ]]; then
	readarray -t CACHE_MOUNTS < <(./scripts/setup-build-cache.sh "$TARGET_TAG")
	BUILD_ARGS+=("${CACHE_MOUNTS[@]}")
fi

PRE_CHUNK_TAG="${TARGET_TAG_WITH_VERSION}-pre-chunk"
echo "==> Building ${DESKTOP_FLAVOR} stage..."

# Pass 1: Build the target DE stage directly — no unused stages built
podman build \
	--security-opt label=disable \
	--dns=8.8.8.8 \
	--platform "$PLATFORM" \
	--target="${DESKTOP_FLAVOR}" \
	"${BUILD_ARGS[@]}" \
	--tag "${PRE_CHUNK_TAG}" \
	--pull=newer \
	--file "$CONTAINERFILE" \
	.

echo "==> Running chunkah on ${PRE_CHUNK_TAG}..."

# Use a clean temp dir to avoid SELinux relabeling issues with existing files in PWD
CHUNK_OUT=$(mktemp -d)
# Pass 2: Run chunkah externally against the built image
podman run --rm \
	--security-opt label=disable \
	--dns=8.8.8.8 \
	--entrypoint="" \
	-v "${CHUNK_OUT}:/run/out:Z" \
	--mount "type=image,source=localhost/${PRE_CHUNK_TAG},target=/chunkah" \
	"$(registry_ref coreos-chunkah 2>/dev/null || echo 'quay.io/coreos/chunkah:latest')" \
	sh -c 'chunkah build > /run/out/out.ociarchive'
mv "${CHUNK_OUT}/out.ociarchive" out.ociarchive
rm -rf "${CHUNK_OUT}"

echo "==> Applying labels from OCI archive..."

# Pass 3: Load archive into podman storage, then apply OCI labels via Containerfile.final.
# Using podman load + tag avoids "FROM oci-archive:" failures on some podman versions
# where the config sha256 is copied but not made available in containers storage.
RECHUNKED_REF="localhost/${TARGET_TAG_WITH_VERSION}-rechunked-$$"
skopeo copy "oci-archive:out.ociarchive" "containers-storage:${RECHUNKED_REF}"

podman build \
	--security-opt label=disable \
	--dns=8.8.8.8 \
	--platform "$PLATFORM" \
	"${BUILD_ARGS[@]}" \
	--build-arg "RECHUNKED_BASE=${RECHUNKED_REF}" \
	--tag "$TARGET_TAG_WITH_VERSION" \
	--file "Containerfile.final" \
	.

podman rmi "${RECHUNKED_REF}" 2>/dev/null || true

# Cleanup
rm -f out.ociarchive
podman rmi "${PRE_CHUNK_TAG}" 2>/dev/null || true

# ── Post-build steps (from 'build' recipe) ─────────────────────────────────

if [[ "$IS_CI" == "0" ]]; then
	./scripts/sync-build-cache.sh "$TARGET_TAG" || true
fi

if [[ "$DID_INIT" == "1" ]]; then
	echo "De-initializing submodules..."
	git submodule deinit -f --all
fi
