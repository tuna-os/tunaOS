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

# Rootless steps (tacklebox drops to the invoking user for podman
# unshare/run, preserving XDG_RUNTIME_DIR) must not share /run/user/<uid>:
# root-context podman ops in the same pipeline can leave root-owned crun
# state there, after which every rootless op dies with "OCI permission
# denied". Hand the dropped user a private, freshly-owned runtime dir.
if [[ $EUID -eq 0 && -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
	XDG_RUNTIME_DIR="/tmp/tbox-xdg-${SUDO_USER}"
	install -d -o "$SUDO_USER" -g "$(id -g "$SUDO_USER")" -m 700 "$XDG_RUNTIME_DIR"
	export XDG_RUNTIME_DIR
elif [[ $EUID -eq 0 ]]; then
	unset XDG_RUNTIME_DIR
fi

# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

# Source registry resolution for TUNA_REGISTRY mirror overrides.
# Falls back to hardcoded ref if _registry.sh is unavailable.
if [[ -f "$(dirname "${BASH_SOURCE[0]}")/_registry.sh" ]]; then
	. "$(dirname "${BASH_SOURCE[0]}")/_registry.sh"
fi

VARIANT="${1:?usage: $0 <variant> <flavor> [repo] [tag]}"
FLAVOR="${2:?usage: $0 <variant> <flavor> [repo] [tag]}"
REPO="${3:-local}"
TAG="${4:-$FLAVOR}"

if [[ "$EUID" -ne 0 ]]; then
	echo "ERROR: tacklebox needs root for sgdisk / mkfs / mount" >&2
	echo "Run: sudo $0 $*" >&2
	exit 1
fi

if [[ ! -d "scripts" ]]; then
	echo "ERROR: run from project root (scripts/ not found in $(pwd))" >&2
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
else
	# Registry image: tacklebox's Pull() lands it in root's store, but the live
	# squash mounts it via `sudo -u $SUDO_USER podman unshare`, which reads the
	# *invoking user's* rootless store (see tacklebox internal/install/{bootc,
	# live}.go). Without this, the squash fails with "image not known". Pre-pull
	# into the user's rootless store so the live path can mount it. The root-side
	# pull tacklebox still does feeds the install/metadata steps that use root's
	# store, so both stores end up with the image. No-op when not under sudo.
	REAL_USER="${SUDO_USER:-}"
	if [[ -n "$REAL_USER" && "$REAL_USER" != "root" ]]; then
		echo "==> Pre-pulling ${IMAGE_REF} into ${REAL_USER}'s rootless store (for live squash)..."
		sudo -u "$REAL_USER" -H podman pull "$IMAGE_REF"
	fi
fi

# ponytail: tacklebox runner delegated to common.sh tunaos_run_tacklebox

# ── Generate the recipe ─────────────────────────────────────────────────────
# Schema: github.com/tuna-os/tacklebox/blob/main/internal/recipe/
# Single-environment, live-only — minimum useful recipe for a smoke ISO.

OUT_DIR="$(pwd)/.build/iso-tacklebox/${VARIANT}-${FLAVOR}"
mkdir -p "$OUT_DIR"
RECIPE_FILE="${OUT_DIR}/recipe.json"

# `desktop` maps an env to its session manager so livesys-* sets autologin
# correctly. Approximation from build_scripts/{gnome,kde,niri,cosmic,xfce}.sh.
DESKTOP="gnome"
case "$FLAVOR" in
kde*) DESKTOP="kde" ;;
niri*) DESKTOP="niri" ;;
cosmic*) DESKTOP="cosmic" ;;
xfce*) DESKTOP="xfce" ;;
gnome* | *) DESKTOP="gnome" ;;
esac

cat >"$RECIPE_FILE" <<EOF
{
  "media_name": "tunaos-${VARIANT}-${FLAVOR}",
  "size": "10G",
  "shared_store": {
    "format": "ext4"
  },
  "kargs": ["console=ttyS0"],
  "bootable_environments": [
    {
      "id": "${VARIANT}-${FLAVOR}",
      "image": "${IMAGE_REF}",
      "desktop": "${DESKTOP}",
      "live_customize": ["${REPO_ROOT}/live-iso/common/src/customize-live.sh"],
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

tunaos_run_tacklebox "$RECIPE_FILE" "$OUT_DIR" "$ISO_OUT"

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
