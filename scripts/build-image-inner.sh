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

# ── Build args ────────────────────────────────────────────────────────────────
BUILD_ARGS=()
BUILD_ARGS+=("--build-arg" "IMAGE_NAME=${PUBLIC_IMAGE_NAME:-$VARIANT}")
BUILD_ARGS+=("--build-arg" "IMAGE_VENDOR=${REPO_ORGANIZATION}")
BUILD_ARGS+=("--build-arg" "IMAGE_REGISTRY=${IMAGE_REGISTRY}")
BUILD_ARGS+=("--build-arg" "BASE_IMAGE=${BASE_IMAGE}")
BUILD_ARGS+=("--build-arg" "COMMON_IMAGE_REF=${common_image_ref}")
BUILD_ARGS+=("--build-arg" "BREW_IMAGE_REF=${brew_image_ref}")
BUILD_ARGS+=("--build-arg" "ENABLE_HWE=${ENABLE_HWE}")
BUILD_ARGS+=("--build-arg" "ENABLE_ASAHI=${ENABLE_ASAHI:-0}")
BUILD_ARGS+=("--build-arg" "ENABLE_NVIDIA=${ENABLE_NVIDIA}")
BUILD_ARGS+=("--build-arg" "DESKTOP_FLAVOR=${DESKTOP_FLAVOR}")
BUILD_ARGS+=("--build-arg" "ENABLE_SSHD=${ENABLE_SSHD}")
BUILD_ARGS+=("--build-arg" "IMAGE_NAME_VARIANT=${VARIANT}")
BOOTC_VERSION=$($YQ -r '.downloads.bootc' image-versions.yaml)
BOOTUPD_VERSION=$($YQ -r '.downloads.bootupd' image-versions.yaml)
BUILD_ARGS+=("--build-arg" "BOOTC_VERSION=${BOOTC_VERSION}")
BUILD_ARGS+=("--build-arg" "BOOTUPD_VERSION=${BOOTUPD_VERSION}")

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
		printf 'export RHSM_USER=%q\n' "${RHSM_USER:-}"
		printf 'export RHSM_PASSWORD=%q\n' "${RHSM_PASSWORD:-}"
		printf 'export RHSM_ORG=%q\n' "${RHSM_ORG:-}"
		printf 'export RHSM_ACTIVATION_KEY=%q\n' "${RHSM_ACTIVATION_KEY:-}"
	} >"${RHSM_SECRET_FILE}"
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

build_primary_image() {
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
}

# Retry the whole build on failure. Two distinct transients, both of which
# reliably succeed on a fresh invocation of the same inputs:
#
#   * Blacksmith's amd64/v2 runners intermittently fail before a Buildah build
#     starts with `open out/index.json: no such file or directory`.
#   * Pulling the base image dies mid-blob against the registry CDN:
#
#       Error: creating build container: copying system image from manifest
#       list: writing blob ...: happened during read: unexpected EOF (while
#       reconnecting: Get "https://cdn01.quay.io/...": EOF)
#
#     LUKS albacore:niri, run 31135329021 — 6 seconds in, on almalinux-bootc.
#
# The retry used to be gated on `BUILDER == buildah`, which is where the
# second one got through: the ISO path builds with podman, so it took the
# `!= buildah` branch and exited after ONE attempt. That is what the log said
# ("image build failed after 1 attempt(s)"), and it reads like an exhausted
# retry rather than an absent one. Nothing about a half-transferred blob is
# specific to a builder, so the gate is gone; the loop is the same otherwise.
build_attempt=1
until build_primary_image; do
	if [[ "${build_attempt}" -ge 3 ]]; then
		echo "ERROR: image build failed after ${build_attempt} attempt(s)" >&2
		exit 1
	fi
	# tuna-os/tunaOS#638: the amd64/v2 failure (`open out/index.json: no such
	# file or directory`) is a buildah containers-storage OCI-layout race; a
	# partially-written container from the failed attempt can fail the same
	# way again. Drop buildah's working containers before retrying.
	if [[ "${BUILDER}" == "buildah" ]]; then
		buildah rm -a >/dev/null 2>&1 || true
	fi
	echo "${BUILDER} build attempt ${build_attempt} failed; retrying in $((build_attempt * 10))s..." >&2
	sleep "$((build_attempt * 10))"
	build_attempt=$((build_attempt + 1))
done

# ── Skip rechunk for PR builds ───────────────────────────────────────────────
if [[ "${SKIP_RECHUNK}" == "1" ]]; then
	echo "==> SKIP_RECHUNK=1 — tagging pre-chunk image as final"
	${BUILDER} tag "${PRE_CHUNK_TAG}" "${IMAGE_TAG}"
	exit 0
fi

# ── Pass 2: Rechunk ──────────────────────────────────────────────────────────
echo "==> Running chunkah on ${PRE_CHUNK_TAG}..."

if [[ -z "${CHUNKAH_IMAGE:-}" ]]; then
	# Pinned (tunaos#1568): every other build input in image-versions.yaml is
	# digest-pinned so an upstream regression needs a reviewed Renovate bump
	# to reach a build. chunkah was the one unpinned :latest exception.
	chunkah_digest=$($YQ -r '.images[] | select(.name == "chunkah") | .digest' image-versions.yaml)
	CHUNKAH_IMAGE="quay.io/coreos/chunkah@${chunkah_digest}"
fi
if ! podman image inspect "${CHUNKAH_IMAGE}" &>/dev/null; then
	if ! podman pull "${CHUNKAH_IMAGE}" 2>/dev/null; then
		echo "==> chunkah image not pullable, building from source..."
		./scripts/build-chunkah.sh
		CHUNKAH_IMAGE="localhost/chunkah:latest"
	fi
fi

# If the target image has no rpmdb (e.g. Debian, Arch), chunkah would fail with
# "error: cannot open Packages database". We enable chunkah on non-RPM images
# by copying the rootfs into container-local workspace, creating a temporary
# /var/lib/rpm directory so chunkah's rpmdb component loader succeeds, and
# passing `--prune /var/lib/rpm` so the dummy directory is never packed into the OCI archive.
#
# `--prune /sysroot/` (both branches, tunaos#1568): bootc images' /sysroot
# holds the ostree deployment tree, which chunkah itself warns is wasted
# bytes if not excluded — "rootfs contains sysroot/ostree which was not
# pruned; Use --prune /sysroot/ to exclude it." The trailing slash matters:
# chunkah's --prune treats `/sysroot` (no slash) as "skip this path
# entirely" and `/sysroot/` (with slash) as "keep the directory, skip its
# children" — /sysroot needs to exist as a mount point at runtime, so this
# repo wants the latter. --prune is a repeatable flag (chunkah's cmd_build.rs
# collects it into a Vec), so this is additive with the existing
# --prune /var/lib/rpm, not a replacement.
#
# chunkah build is retried once (CHUNKAH_ATTEMPT loop) because a corrupt
# out.ociarchive has been observed once so far (tunaos#1568: "archive/tar:
# invalid tar header" at the podman load step below, bonito:base
# 2026-08-14) with no confirmed root cause -- possibly a truncated write
# under disk pressure. `tar tf` validates the archive is at least a well-
# formed tarball before handing it to podman load, so a truncated write is
# caught here with a log line pointing at this issue, instead of surfacing
# as podman's much less obvious "payload does not match any of the
# supported image formats".
CHUNKAH_OK=0
for CHUNKAH_ATTEMPT in 1 2; do
	CHUNK_OUT=$(mktemp -d)
	CHUNK_EMPTY_DEV=$(mktemp -d)
	podman run --rm \
		--security-opt label=disable \
		--network host \
		--entrypoint="" \
		-v "${CHUNK_OUT}:/run/out:Z" \
		--mount "type=image,source=${PRE_CHUNK_TAG},target=/chunkah" \
		-v "${CHUNK_EMPTY_DEV}:/chunkah/dev:Z" \
		"${CHUNKAH_IMAGE}" \
		sh -c '
			HAS_RPMDB=0
			if [ -n "$(ls -A /chunkah/usr/lib/sysimage/rpm 2>/dev/null)" ] || [ -n "$(ls -A /chunkah/var/lib/rpm 2>/dev/null)" ]; then
				HAS_RPMDB=1
			fi
			if [ "$HAS_RPMDB" = "1" ]; then
				chunkah build --rootfs /chunkah --prune /sysroot/ --skip-special-files -o /run/out/out.ociarchive
			else
				echo "==> Image has no rpmdb — preparing rootfs copy with dummy rpmdb & pruning it in chunkah build..."
				mkdir -p /tmp/rootfs
				cp -a /chunkah/. /tmp/rootfs/
				mkdir -p /tmp/rootfs/var/lib/rpm
				chunkah build --rootfs /tmp/rootfs --prune /var/lib/rpm --prune /sysroot/ --skip-special-files -o /run/out/out.ociarchive
				rm -rf /tmp/rootfs
			fi
		'
	if [[ -s "${CHUNK_OUT}/out.ociarchive" ]] && tar tf "${CHUNK_OUT}/out.ociarchive" >/dev/null 2>&1; then
		mv "${CHUNK_OUT}/out.ociarchive" out.ociarchive
		rm -rf "${CHUNK_OUT}" "${CHUNK_EMPTY_DEV}"
		CHUNKAH_OK=1
		break
	fi
	echo "::warning::chunkah attempt ${CHUNKAH_ATTEMPT}/2 produced an invalid or missing out.ociarchive (tunaos#1568) — retrying" >&2
	rm -rf "${CHUNK_OUT}" "${CHUNK_EMPTY_DEV}"
done
if [[ "${CHUNKAH_OK}" -ne 1 ]]; then
	echo "ERROR: chunkah did not produce a valid OCI archive after 2 attempts" >&2
	exit 1
fi

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
