#!/usr/bin/env bash
# Build a TunaOS live ISO using the bootc-isos approach (Ondrej Budai).
# Must be run as root (uses privileged containers and /var/lib/containers/storage).
#
# Usage: sudo ./scripts/build-live-iso.sh <variant> <flavor> <repo> [tag]
#   variant  - yellowfin | albacore | skipjack | bonito
#   flavor   - gnome | kde | gnome-hwe | etc.
#   repo     - local | ghcr
#   tag      - image tag (default: <flavor>)

set -euo pipefail

# Special mode: just build the image-builder-dev container and exit
if [ "${1:-}" = "--build-image-builder-only" ]; then
	shift
	# Fall through to the image-builder build step; set dummy vars so the rest is skipped
	VARIANT="" FLAVOR="" REPO="" TAG="" _BUILD_ONLY=1
fi
_BUILD_ONLY="${_BUILD_ONLY:-0}"

if [ "$EUID" -ne 0 ]; then
	echo "This script must be run as root (uses privileged podman)." >&2
	echo "Run: sudo $0 $*" >&2
	exit 1
fi

if [ ! -d "live-iso" ]; then
	echo "Must be run from project root (live-iso/ not found in $(pwd))" >&2
	exit 1
fi

IMAGE_BUILDER_DEV="image-builder-dev"

if [ "$_BUILD_ONLY" = "0" ]; then
	VARIANT="${1:-skipjack}"
	FLAVOR="${2:-gnome}"
	REPO="${3:-local}"
	TAG="${4:-${FLAVOR}}"

	case "$VARIANT" in
	"yellowfin") LABEL="Yellowfin-Live" ;;
	"albacore") LABEL="Albacore-Live" ;;
	"skipjack") LABEL="Skipjack-Live" ;;
	"bonito") LABEL="Bonito-Live" ;;
	*) LABEL="TunaOS-Live" ;;
	esac

	GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
	INSTALLER_TAG="${VARIANT}-${FLAVOR}-installer"
	OUTPUT_DIR="$(pwd)/.build/live-iso/${VARIANT}-${FLAVOR}"

	case "$REPO" in
	local)
		BASE_IMAGE="localhost/${VARIANT}:${FLAVOR}"
		PAYLOAD_REF="localhost/${VARIANT}:${FLAVOR}"
		;;
	ghcr)
		BASE_IMAGE="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${VARIANT}:${TAG}"
		PAYLOAD_REF="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${VARIANT}:${TAG}"
		;;
	registry)
		REGISTRY="${REGISTRY:-localhost:5000}"
		BASE_IMAGE="${REGISTRY}/${VARIANT}:${FLAVOR}"
		PAYLOAD_REF="${REGISTRY}/${VARIANT}:${FLAVOR}"
		;;
	*)
		echo "Unknown repo '${REPO}'. Use 'local', 'ghcr', or 'registry'." >&2
		exit 1
		;;
	esac
fi

# ── Step 0: ensure local image is available in root podman storage ───────────

if [ "$REPO" = "local" ] && ! podman image exists "$BASE_IMAGE"; then
	echo "==> $BASE_IMAGE not in root podman storage."
	echo "==> Trying to import from the invoking user's storage..."
	REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo '')}"
	if [ -n "$REAL_USER" ]; then
		sudo -u "$REAL_USER" podman save "$BASE_IMAGE" | podman load
	else
		echo "ERROR: cannot find the original user to import from." >&2
		echo "Build as root: sudo just build ${VARIANT} ${FLAVOR}" >&2
		exit 1
	fi
fi

# ── Step 1: build image-builder-dev container ───────────────────────────────
# We need Ondrej's fork of image-builder-cli that supports bootc-generic-iso.
# Pinned to a known-good commit with extra patches from PR#5.

if ! podman image exists "$IMAGE_BUILDER_DEV"; then
	echo "==> Building image-builder-dev..."
	WORKDIR=$(mktemp -d)
	trap 'rm -rf "$WORKDIR"' EXIT

	git clone https://github.com/osbuild/image-builder-cli.git "$WORKDIR/image-builder-cli"
	pushd "$WORKDIR/image-builder-cli"

	# Pin to commit that supports bootc-generic-iso
	git reset --hard cf20ed6a417c5e4dd195b34967cd2e4d5dc7272f

	# Patch: don't fail when /dev devtmpfs mount fails in privileged containers
	sed -i '/mount.*devtmpfs.*devtmpfs.*\/dev/,/return err/ s/return err/log.Printf("check: failed to mount \/dev: %v", err)/' \
		pkg/setup/setup.go

	# Find go binary (handles Homebrew installs)
	if command -v go &>/dev/null; then
		GO_BIN="go"
	elif [ -x "/home/linuxbrew/.linuxbrew/bin/go" ]; then
		GO_BIN="/home/linuxbrew/.linuxbrew/bin/go"
	else
		echo "ERROR: go not found. Install with: sudo apt-get install golang-go" >&2
		exit 1
	fi

	$GO_BIN mod tidy
	$GO_BIN mod edit -replace github.com/osbuild/images=github.com/ondrejbudai/images@bootc-generic-iso-dev
	$GO_BIN get github.com/osbuild/blueprint@v1.22.0
	GOPROXY=direct $GO_BIN mod tidy

	podman build \
		--security-opt label=disable \
		--security-opt seccomp=unconfined \
		-t "$IMAGE_BUILDER_DEV" .

	popd
	trap - EXIT
	rm -rf "$WORKDIR"
	echo "==> image-builder-dev built."
else
	echo "==> image-builder-dev already present, skipping build."
fi

[ "$_BUILD_ONLY" = "1" ] && exit 0

# ── Step 2: build installer container ────────────────────────────────────────

echo "==> Building installer container: ${INSTALLER_TAG} (base: ${BASE_IMAGE})"
podman build \
	--cap-add sys_admin \
	--security-opt label=disable \
	--build-arg "BASE_IMAGE=${BASE_IMAGE}" \
	--build-arg "LABEL=${LABEL}" \
	--build-arg "VARIANT=${VARIANT}" \
	--build-arg "DESKTOP_FLAVOR=${FLAVOR}" \
	--build-arg "ENABLE_SSHD=${DEV_SSHD:-0}" \
	-t "localhost/${INSTALLER_TAG}" \
	-f live-iso/common/Containerfile \
	live-iso/common

# ── Step 3: generate osbuild manifest ────────────────────────────────────────

mkdir -p "$OUTPUT_DIR"

echo "==> Generating osbuild manifest..."
podman run --rm --privileged \
	-v /var/lib/containers/storage:/var/lib/containers/storage \
	--entrypoint /usr/bin/image-builder \
	"$IMAGE_BUILDER_DEV" \
	manifest \
	--bootc-ref "localhost/${INSTALLER_TAG}" \
	--bootc-installer-payload-ref "${PAYLOAD_REF}" \
	--bootc-default-fs ext4 \
	bootc-generic-iso \
	>"${OUTPUT_DIR}/manifest.json"

# ── Step 4: patch manifest (remove-signatures) ───────────────────────────────
# skopeo stages need remove-signatures=true when the image has no cosign sig.

echo "==> Patching manifest (remove-signatures)..."
jq '(.pipelines[] | .stages[]? | select(.type == "org.osbuild.skopeo") | .options) += {"remove-signatures": true}' \
	"${OUTPUT_DIR}/manifest.json" >"${OUTPUT_DIR}/manifest-patched.json"

# ── Step 5: build ISO with osbuild ───────────────────────────────────────────

echo "==> Building ISO with osbuild..."
podman run --rm --privileged \
	-v /var/lib/containers/storage:/var/lib/containers/storage \
	-v "${OUTPUT_DIR}:/output:Z" \
	-i \
	--entrypoint /usr/bin/osbuild \
	"$IMAGE_BUILDER_DEV" \
	--output-directory /output \
	--export bootiso \
	- <"${OUTPUT_DIR}/manifest-patched.json"

# ── Step 6: rename ISO ────────────────────────────────────────────────────────

echo "==> Renaming ISO..."
VERSION_ID=$(podman run --rm --security-opt label=disable \
	"localhost/${INSTALLER_TAG}" \
	sh -c '. /usr/lib/os-release && echo "${VERSION_ID}"')
ARCH=$(podman run --rm --security-opt label=disable \
	"localhost/${INSTALLER_TAG}" uname -m)

FINAL_ISO="${VARIANT}-${FLAVOR}-${VERSION_ID}-${ARCH}.iso"
mv "${OUTPUT_DIR}/bootiso/install.iso" "${FINAL_ISO}"

echo ""
echo "==> Done! ISO: ${FINAL_ISO}"

# ── Optional: upload to R2 ───────────────────────────────────────────────────

if [ "${UPLOAD_R2:-false}" = "true" ]; then
	echo "==> Uploading to Cloudflare R2..."
	rclone copy --log-level INFO --checksum --s3-no-check-bucket \
		"./${FINAL_ISO}" R2:"${R2_BUCKET}"/live-isos/
	LATEST_ISO="${VARIANT}-${FLAVOR}-latest.iso"
	rclone copyto --log-level INFO --s3-no-check-bucket \
		"./${FINAL_ISO}" "R2:${R2_BUCKET}/live-isos/${LATEST_ISO}"
	echo "==> Uploaded (versioned + latest)."
fi
