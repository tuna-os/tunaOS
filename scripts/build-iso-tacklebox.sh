#!/usr/bin/env bash
# scripts/build-iso-tacklebox.sh — build a TunaOS live ISO via tacklebox.
#
# tacklebox (https://github.com/tuna-os/tacklebox) is a Go-based bootc →
# bootable-media orchestrator. Its `--iso` target produces a UEFI live ISO
# from a bootc OCI ref with no anaconda dependency (uses systemd-boot +
# dmsquash-live). This replaces the previous osbuild image-builder-cli
# approach for simpler, more reliable ISO generation.
#
# Usage:
#   sudo ./scripts/build-iso-tacklebox.sh <variant> <flavor> [<repo>] [<tag>]
#     variant   yellowfin | albacore | skipjack | bonito
#     flavor    base | gnome | gnome-hwe | kde | …
#     repo      local | ghcr   (default: local)
#     tag       defaults to <flavor>
#
# Outputs to project root as <variant>-<flavor>-<version>-<arch>.iso

set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

VARIANT="${1:?usage: $0 <variant> <flavor> [repo] [tag]}"
FLAVOR="${2:?usage: $0 <variant> <flavor> [repo] [tag]}"
REPO="${3:-local}"
TAG="${4:-$FLAVOR}"

if [[ "$EUID" -ne 0 ]]; then
	echo "ERROR: tacklebox needs root for sgdisk / mkfs / mount" >&2
	echo "Run: sudo $0 $*" >&2
	exit 1
fi

if [[ ! -d "live-iso" ]]; then
	echo "ERROR: run from project root (live-iso/ not found in $(pwd))" >&2
	exit 1
fi

# Store the project root for later use when copying ISOs
REPO_ROOT="$(pwd)"

# ── Resolve the source bootc image ref ──────────────────────────────────────
# tunaos_image_ref + tunaos_import_to_root_storage are defined in
# scripts/lib/common.sh.

IMAGE_REF=$(tunaos_image_ref "$VARIANT" "$FLAVOR" "$REPO" "$TAG")
if [[ "$REPO" == "local" ]]; then
	tunaos_import_to_root_storage "$IMAGE_REF"
fi

# ── Resolve tacklebox: prefer the published container, fall back to source ──
# Published image: ghcr.io/tuna-os/tacklebox:latest (multi-arch). Use that by
# default so this script needs no Go toolchain. Set TACKLEBOX_FROM_SOURCE=1
# to opt into the source build (helpful when iterating on tacklebox itself
# locally before a tag is cut).

TACKLEBOX_IMAGE="${TACKLEBOX_IMAGE:-ghcr.io/tuna-os/tacklebox:latest}"
TACKLEBOX_FROM_SOURCE="${TACKLEBOX_FROM_SOURCE:-0}"

if [[ "$TACKLEBOX_FROM_SOURCE" == "1" ]]; then
	# Pin the source SHA when building from main so CI doesn't silently
	# track a moving HEAD. Bump via renovate when a release is cut.
	TACKLEBOX_SHA="${TACKLEBOX_SHA:-$(grep '^\s*tacklebox:' image-versions.yaml | sed 's/.*"\(.*\)".*/\1/')}"
	TACKLEBOX_SHA="${TACKLEBOX_SHA:-75c837b39d9dcb360509c49d2e0306621dced904}"
	TACKLEBOX_CACHE="${TACKLEBOX_CACHE:-/var/cache/tunaos/tacklebox}"
	TACKLEBOX_BIN="${TACKLEBOX_CACHE}/tacklebox"

	if [[ ! -x "$TACKLEBOX_BIN" ]] || [[ "$("$TACKLEBOX_BIN" version 2>/dev/null || echo)" != *"$TACKLEBOX_SHA"* ]]; then
		echo "==> Building tacklebox @ ${TACKLEBOX_SHA}..."
		mkdir -p "$TACKLEBOX_CACHE"
		cd "$TACKLEBOX_CACHE"
		if [[ ! -d .git ]]; then
			git clone --quiet https://github.com/tuna-os/tacklebox.git .
		else
			git fetch --quiet origin
		fi
		git -c advice.detachedHead=false checkout --quiet "$TACKLEBOX_SHA"
		GO_BIN=""
		for g in /home/linuxbrew/.linuxbrew/bin/go /usr/bin/go go; do
			if command -v "$g" &>/dev/null; then
				GO_BIN="$g"
				break
			fi
		done
		if [[ -z "$GO_BIN" ]]; then
			echo "ERROR: go not found; install go 1.22+ to build tacklebox" >&2
			exit 1
		fi
		"$GO_BIN" build -o tacklebox ./cmd/tacklebox
		cd - >/dev/null
	fi
	if [[ ! -x "$TACKLEBOX_BIN" ]]; then
		echo "ERROR: tacklebox binary missing after build" >&2
		exit 1
	fi
	# Adapter so the rest of the script doesn't care which path we took.
	tacklebox() { "$TACKLEBOX_BIN" "$@"; }
else
	echo "==> Using tacklebox image: ${TACKLEBOX_IMAGE}"
	podman pull "$TACKLEBOX_IMAGE" >/dev/null

	# Tacklebox needs:
	#   * /var/lib/containers/storage so it can pull the source bootc image
	#     into the same root store we already populated above;
	#   * /dev for loopback + sgdisk (the container runs --privileged);
	#   * the recipe + output dir bind-mounted in.
	# Adapter runs the published image with those mounts in place.
	tacklebox() {
		podman run --rm --privileged \
			--security-opt label=disable \
			-v /var/lib/containers:/var/lib/containers \
			-v /dev:/dev \
			-v "$(realpath "$OUT_DIR"):$(realpath "$OUT_DIR")" \
			-v "$(realpath "$RECIPE_FILE"):$(realpath "$RECIPE_FILE"):ro" \
			"$TACKLEBOX_IMAGE" "$@"
	}
fi

# ── Generate the recipe ─────────────────────────────────────────────────────
# Schema: github.com/tuna-os/tacklebox/blob/main/internal/recipe/
# Single-environment, live-only — minimum useful recipe for a smoke ISO.

OUT_DIR=".build/iso-tacklebox/${VARIANT}-${FLAVOR}"
mkdir -p "$OUT_DIR"
RECIPE_FILE="${OUT_DIR}/recipe.json"

# `desktop` maps an env to its session manager so livesys-* sets autologin
# correctly. Approximation from build_scripts/{gnome,kde,niri,cosmic}.sh.
DESKTOP="gnome"
case "$FLAVOR" in
kde*) DESKTOP="kde" ;;
niri*) DESKTOP="niri" ;;
cosmic*) DESKTOP="cosmic" ;;
gnome* | *) DESKTOP="gnome" ;;
esac

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

# ── Invoke tacklebox ────────────────────────────────────────────────────────

ISO_OUT="${OUT_DIR}/tunaos-${VARIANT}-${FLAVOR}.iso"
echo "==> Building ISO with tacklebox..."
echo "    image:  ${IMAGE_REF}"
echo "    recipe: ${RECIPE_FILE}"
echo "    output: ${ISO_OUT}"

tacklebox build "$RECIPE_FILE" \
	--iso "$ISO_OUT" \
	--output-base "$OUT_DIR" \
	--yes

# Hand ownership back to the invoking user so the ISO is usable without sudo.
if [[ -n "${SUDO_USER:-}" ]]; then
	chown "${SUDO_UID:-$(id -u "$SUDO_USER")}:${SUDO_GID:-$(id -g "$SUDO_USER")}" "$ISO_OUT" || true
fi

# ── Copy ISO to project root (matching publish-isos expectations) ──────────────
# Copy to project root with version info in filename (matching bootc-image-builder pattern)
cd - >/dev/null
REPO_ROOT="${REPO_ROOT:-.}"
VERSION_ID=$(podman run --rm --security-opt label=disable \
	"$IMAGE_REF" \
	sh -c '. /usr/lib/os-release && echo "${VERSION_ID}"')
ARCH=$(podman run --rm --security-opt label=disable \
	"$IMAGE_REF" uname -m)

FINAL_ISO="${REPO_ROOT}/${VARIANT}-${FLAVOR}-${VERSION_ID}-${ARCH}.iso"
cp "$ISO_OUT" "$FINAL_ISO"

if [[ -n "${SUDO_USER:-}" ]]; then
	chown "${SUDO_UID:-$(id -u "$SUDO_USER")}:${SUDO_GID:-$(id -g "$SUDO_USER")}" "$FINAL_ISO" || true
fi

echo ""
echo "==> Done! ISO: ${FINAL_ISO} ($(du -h "$FINAL_ISO" | cut -f1))"
