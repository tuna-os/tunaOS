#!/usr/bin/env bash
# scripts/build-iso-group.sh — build ONE combined live ISO containing several
# desktop environments via tacklebox dedup (issue #455).
#
# tacklebox `shared_store.dedup` packs every bootable environment into a single
# shared squashfs. All desktops on a variant share the same Enterprise-Linux
# base, so dedup is ~80%+ — an extra desktop costs ~300 MB instead of a whole
# new ISO. The systemd-boot menu lists each environment by title; the user
# picks a desktop at boot.
#
# Groups are defined under `iso_groups:` in .github/build-config.yml. This
# script intersects a group's flavor list with the variant's actual
# `build_image: true` flavors, so variants that lack a desktop simply get a
# smaller ISO.
#
# Usage:
#   sudo ./scripts/build-iso-group.sh <variant> <group> [<repo>]
#     variant   yellowfin | albacore | skipjack | bonito
#     group     ""|default (flagship), community, nvidia, … (a suffix in iso_groups)
#     repo      local | ghcr   (default: ghcr)
#
# Outputs to project root as <variant>[-<group>]-<version>-<arch>.iso
#   e.g. yellowfin.iso → yellowfin-10.0-x86_64.iso
#        yellowfin-community-10.0-x86_64.iso

set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

VARIANT="${1:?usage: $0 <variant> <group> [repo]}"
# "default"/"flagship"/"" all select the empty-suffix flagship group.
GROUP_RAW="${2-default}"
REPO="${3:-ghcr}"

CONFIG=".github/build-config.yml"

if [[ "$EUID" -ne 0 ]]; then
	echo "ERROR: tacklebox needs root for sgdisk / mkfs / mount" >&2
	echo "Run: sudo $0 $*" >&2
	exit 1
fi

if [[ ! -d "live-iso" ]]; then
	echo "ERROR: run from project root (live-iso/ not found in $(pwd))" >&2
	exit 1
fi

for tool in yq jq podman; do
	command -v "$tool" >/dev/null 2>&1 || {
		echo "ERROR: required tool '$tool' not found in PATH" >&2
		exit 1
	}
done

REPO_ROOT="$(pwd)"

# Normalise the group selector to its config suffix ("" for the flagship).
case "$GROUP_RAW" in
default | flagship | "") GROUP_SUFFIX="" ;;
*) GROUP_SUFFIX="$GROUP_RAW" ;;
esac

# ── Resolve the flavor list for this (variant, group) ───────────────────────
# group_flavors: what the group asks for, in priority order (first = default
#                boot entry).
# variant_flavors: what the variant can actually build.
# selected = group_flavors ∩ variant_flavors, preserving group order.
CONFIG_JSON="$(yq -o=json '.' "$CONFIG")"

if ! echo "$CONFIG_JSON" | jq -e --arg s "$GROUP_SUFFIX" \
	'.iso_groups[] | select((.suffix // "") == $s)' >/dev/null; then
	echo "ERROR: no iso_group with suffix '${GROUP_SUFFIX}' in $CONFIG" >&2
	echo "Available groups:" >&2
	echo "$CONFIG_JSON" | jq -r '.iso_groups[] | "  - \(.suffix // "" | if . == "" then "(flagship)" else . end)"' >&2
	exit 1
fi

mapfile -t GROUP_FLAVORS < <(echo "$CONFIG_JSON" | jq -r --arg s "$GROUP_SUFFIX" \
	'.iso_groups[] | select((.suffix // "") == $s) | .flavors[]')

mapfile -t VARIANT_FLAVORS < <(echo "$CONFIG_JSON" | jq -r --arg v "$VARIANT" \
	'.variants[] | select(.id == $v) | .flavors[] | select(.build_image == true) | .id')

if ((${#VARIANT_FLAVORS[@]} == 0)); then
	echo "ERROR: unknown variant '${VARIANT}' (no flavors in $CONFIG)" >&2
	exit 1
fi

# Intersect, preserving group order.
SELECTED=()
for f in "${GROUP_FLAVORS[@]}"; do
	for v in "${VARIANT_FLAVORS[@]}"; do
		if [[ "$f" == "$v" ]]; then
			SELECTED+=("$f")
			break
		fi
	done
done

if ((${#SELECTED[@]} == 0)); then
	echo "==> No flavors from group '${GROUP_SUFFIX:-flagship}' are built for ${VARIANT}; nothing to do." >&2
	exit 0
fi

# ── Names ───────────────────────────────────────────────────────────────────
if [[ -n "$GROUP_SUFFIX" ]]; then
	ISO_BASENAME="${VARIANT}-${GROUP_SUFFIX}"
	MEDIA_NAME="TunaOS ${VARIANT^} ${GROUP_SUFFIX^}"
else
	ISO_BASENAME="${VARIANT}"
	MEDIA_NAME="TunaOS ${VARIANT^}"
fi

echo "==> Building grouped ISO '${ISO_BASENAME}' for ${VARIANT}"
echo "    environments: ${SELECTED[*]}"

# ── Build the recipe ────────────────────────────────────────────────────────
OUT_DIR=".build/iso-group/${ISO_BASENAME}"
mkdir -p "$OUT_DIR"
RECIPE_FILE="${OUT_DIR}/recipe.json"

# Assemble the bootable_environments array with jq so quoting/escaping is safe.
ENVS_JSON="[]"
FIRST_REF=""
for flavor in "${SELECTED[@]}"; do
	ref="$(tunaos_image_ref "$VARIANT" "$flavor" "$REPO" "$flavor")"
	[[ -z "$FIRST_REF" ]] && FIRST_REF="$ref"
	# Pull local images into root storage so tacklebox can read them.
	if [[ "$REPO" == "local" ]]; then
		tunaos_import_to_root_storage "$ref"
	fi
	ENVS_JSON="$(jq -c \
		--arg id "${VARIANT}-${flavor}" \
		--arg image "$ref" \
		--arg title "$(tunaos_flavor_title "$flavor")" \
		--arg desktop "$(tunaos_flavor_desktop "$flavor")" \
		'. + [{id: $id, image: $image, title: $title, desktop: $desktop, modes: ["live"]}]' \
		<<<"$ENVS_JSON")"
done

jq -n \
	--arg media_name "$MEDIA_NAME" \
	--argjson envs "$ENVS_JSON" \
	'{
		media_name: $media_name,
		shared_store: { dedup: true, compression: "release" },
		bootable_environments: $envs
	}' >"$RECIPE_FILE"

echo "==> Recipe:"
cat "$RECIPE_FILE"

# ── Build ───────────────────────────────────────────────────────────────────
ISO_OUT="${OUT_DIR}/${ISO_BASENAME}.iso"
echo "==> Building combined ISO with tacklebox..."
tunaos_run_tacklebox "$RECIPE_FILE" "$OUT_DIR" "$ISO_OUT"

# Hand ownership back to the invoking user.
chown_back() {
	[[ -n "${SUDO_USER:-}" ]] || return 0
	chown "${SUDO_UID:-$(id -u "$SUDO_USER")}:${SUDO_GID:-$(id -g "$SUDO_USER")}" "$1" 2>/dev/null || true
}
chown_back "$ISO_OUT"

# ── Copy to project root with version/arch in the name ──────────────────────
# Use the first (default) environment's image to read VERSION_ID + arch — all
# environments share the same EL base, so any of them gives the same answer.
VERSION_ID=$(podman run --rm --security-opt label=disable "$FIRST_REF" \
	sh -c '. /usr/lib/os-release && echo "${VERSION_ID}"')
ARCH=$(podman run --rm --security-opt label=disable "$FIRST_REF" uname -m)

FINAL_ISO="${REPO_ROOT}/${ISO_BASENAME}-${VERSION_ID}-${ARCH}.iso"
cp "$ISO_OUT" "$FINAL_ISO"
chown_back "$FINAL_ISO"

echo ""
echo "==> Done! ISO: ${FINAL_ISO} ($(du -h "$FINAL_ISO" | cut -f1))"
echo "    boot menu: ${SELECTED[*]}"
