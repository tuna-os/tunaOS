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
	# Keep this default equal to the Justfile's (Justfile:5). Nothing in
	# .github/workflows sets COREOS_STABLE_VERSION, and every real build goes
	# through `just`, which exports it — so this fallback only fires when the
	# script is invoked directly, which is exactly why it sat two Fedora
	# releases behind (41) without anyone noticing. tests/bats/
	# test_fedora_base_currency.bats now compares the two (tunaOS#1171).
	COREOS_STABLE="${COREOS_STABLE_VERSION:-43}"
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

# Resolve through registry-map.yaml rather than hardcoding a ref, so chunkah
# comes in digest-pinned like every other build input. registry-map.yaml has
# carried a coreos-chunkah digest (with a "prevent supply-chain attacks via tag
# mutation" comment) the whole time; registry_ref just could not read it —
# see the digest-override note in scripts/_registry.sh (tunaOS#1568). An
# unpinned :latest meant an upstream chunkah regression landed in our builds
# the hour it was published, unreviewed, which is one of the two candidate
# causes for the corrupt archive this block now also detects.
if [[ -z "${CHUNKAH_IMAGE:-}" ]]; then
	CHUNKAH_IMAGE="$(registry_ref coreos-chunkah)"
fi
echo "==> chunkah image: ${CHUNKAH_IMAGE}"
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
# `--prune /sysroot/` — note the TRAILING SLASH. chunkah's scanner documents
# it as load-bearing:
#
#   "Paths must be absolute. A trailing `/` means prune children only,
#    keeping the directory itself."               (chunkah src/scan.rs)
#
# so `--prune /sysroot` (no slash) would drop the /sysroot directory itself,
# which a bootc image needs as the real sysroot's mountpoint. Upstream's own
# warning — the one bonito's log printed — spells it with the slash:
# "Use --prune /sysroot/ to exclude it". Chunking an ostree object store
# "produces poor results" per that warning, and packs bytes no deployment
# reads. `prune` is a Vec, so it can be passed more than once.
#
# It goes on BOTH branches. The rpmdb branch — the one every RPM variant takes,
# bonito included — passed no --prune at all, so the sysroot has been packed
# into every rechunked RPM image.
chunkah_attempt() {
	local out_dir="$1"
	podman run --rm \
		--security-opt label=disable \
		--network host \
		--entrypoint="" \
		-v "${out_dir}:/run/out:Z" \
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
}

# chunkah reported "build complete" and still produced an archive that podman
# could not read ("archive/tar: invalid tar header" mid-blob, bonito base
# 2026-08-14). A zero exit from the builder is therefore not evidence the
# archive is loadable — check the container that podman is about to consume
# before consuming it, so a truncated write is named where it happens rather
# than surfacing as an opaque `podman load` error two steps later.
validate_ociarchive() {
	local f="$1" listing
	if [[ ! -s "$f" ]]; then
		echo "==> archive is missing or empty" >&2
		return 1
	fi
	# oci-archive is a plain (uncompressed) tar, so listing it walks every
	# header — exactly the read that failed. Capture the listing instead of
	# piping it: `tar tf ... | grep -q` lets grep exit at the first match, tar
	# takes SIGPIPE, and under this script's `set -o pipefail` the pipeline
	# then reports failure for a perfectly good archive. The listing is
	# filenames only (an oci-archive has a handful of entries), not content.
	if ! listing="$(tar tf "$f" 2>&1)"; then
		echo "==> archive does not read as a valid tar:" >&2
		printf '%s\n' "$listing" | tail -3 >&2
		return 1
	fi
	# The whole "./" is optional, not just its slash: `tar cf x -C d .` lists
	# entries as ./oci-layout while `tar cf x -C d oci-layout ...` lists them
	# bare, and both are valid OCI archives. `^\./?oci-layout$` would demand
	# the dot and reject the second form — verified against real tarballs of
	# each shape rather than reasoned about.
	if ! grep -qE '^(\./)?oci-layout$' <<<"$listing"; then
		echo "==> archive is a valid tar but has no oci-layout — not an OCI archive" >&2
		return 1
	fi
	return 0
}

# Disk pressure is the other candidate cause: the uncompressed archive is
# several GiB and is written before the prune below frees space. Report it
# rather than guess — one line that either confirms or kills that hypothesis
# the next time this fails.
echo "==> free space before rechunk:"
df -Ph "${TMPDIR:-/tmp}" . 2>/dev/null || true

CHUNK_EMPTY_DEV=$(mktemp -d)
CHUNK_OUT=""
rechunk_ok=0
for attempt in 1 2; do
	# CHUNK_OUT is empty on the first pass, so this is a no-op then and a
	# cleanup of the previous attempt's partial archive on the second —
	# attempt 2 must not end up validating attempt 1's corpse.
	#
	# Spelled as `if` rather than `[[ -n ... ]] && rm`: under `set -e` the &&
	# form is exempt here only because another statement follows it, and it
	# would start failing the build if it were ever moved to the end of a
	# function or loop body. Not worth leaving that dependency on line order.
	if [[ -n "${CHUNK_OUT}" ]]; then
		rm -rf "${CHUNK_OUT}"
	fi
	CHUNK_OUT=$(mktemp -d)
	echo "==> chunkah build (attempt ${attempt}/2)"
	if chunkah_attempt "${CHUNK_OUT}" && validate_ociarchive "${CHUNK_OUT}/out.ociarchive"; then
		rechunk_ok=1
		break
	fi
	echo "::warning::chunkah attempt ${attempt} produced no usable oci-archive" >&2
	df -Ph "${TMPDIR:-/tmp}" . 2>/dev/null || true
done
if [[ "${rechunk_ok}" -ne 1 ]]; then
	echo "ERROR: chunkah produced an unreadable oci-archive twice — not loading it." >&2
	echo "       A corrupt archive here is a truncated/interrupted write, not a" >&2
	echo "       recoverable image; loading it fails later with a far less" >&2
	echo "       obvious 'invalid tar header' (tunaOS#1568)." >&2
	rm -rf "${CHUNK_OUT}" "${CHUNK_EMPTY_DEV}"
	exit 1
fi

mv "${CHUNK_OUT}/out.ociarchive" out.ociarchive
rm -rf "${CHUNK_OUT}" "${CHUNK_EMPTY_DEV}"

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
