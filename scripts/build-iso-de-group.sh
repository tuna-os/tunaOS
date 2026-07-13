#!/usr/bin/env bash
# scripts/build-iso-de-group.sh — EXPERIMENT: build ONE combined live ISO that
# packs the same desktop environment across multiple variants via tacklebox dedup
# (experiment/de-grouped-isos, see .github/build-config.yml de_iso_groups).
#
# Hypothesis: the DE layer is the largest unique chunk. Grouping multiple EL
# bases under ONE DE stack should produce smaller ISOs than grouping multiple
# DE stacks under one EL base (the current variant-centric approach).
#
# The group's `environments` list declares (variant, flavor) pairs in boot-menu
# order. Any pair where the flavor lacks `build_image: true` in the config is
# silently skipped (so a partial config just produces a smaller ISO).
#
# Usage:
#   sudo ./scripts/build-iso-de-group.sh <de-id> [repo]
#     de-id   gnome | kde | cosmic | niri   (an id in de_iso_groups)
#     repo    local | ghcr  (default: ghcr)
#
# Output ISO: tuna-<de-id>[-<version>]-<arch>.iso in the project root.

set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

DE_ID="${1:?usage: $0 <de-id> [repo]}"
REPO="${2:-ghcr}"

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
CONFIG_JSON="$(yq -o=json '.' "$CONFIG")"

# ── Validate the de_iso_group exists ────────────────────────────────────────
if ! echo "$CONFIG_JSON" | jq -e --arg id "$DE_ID" \
	'.de_iso_groups[] | select(.id == $id)' >/dev/null 2>&1; then
	echo "ERROR: no de_iso_group with id '${DE_ID}' in $CONFIG" >&2
	echo "Available groups:" >&2
	echo "$CONFIG_JSON" | jq -r '.de_iso_groups[] | "  - \(.id)"' >&2
	exit 1
fi

GROUP_TITLE="$(echo "$CONFIG_JSON" | jq -r --arg id "$DE_ID" \
	'.de_iso_groups[] | select(.id == $id) | .title')"

# ── Build list of all variant flavors that have build_image: true ────────────
# Returns a lookup of "variant:flavor" pairs that can actually be built.
declare -A BUILDABLE
while IFS=: read -r v f; do
	BUILDABLE["${v}:${f}"]=1
done < <(echo "$CONFIG_JSON" | jq -r '
	.variants[] as $var
	| ($var.id) as $vid
	| $var.flavors[]
	| select(.build_image == true)
	| "\($vid):\(.id)"')

# ── Resolve selected environments ────────────────────────────────────────────
# Read environments from config; skip pairs not present in BUILDABLE.
mapfile -t RAW_ENVS < <(echo "$CONFIG_JSON" | jq -r --arg id "$DE_ID" \
	'.de_iso_groups[] | select(.id == $id) | .environments[] | "\(.variant):\(.flavor)"')

mapfile -t RAW_OFFLINE < <(echo "$CONFIG_JSON" | jq -r --arg id "$DE_ID" \
	'.de_iso_groups[] | select(.id == $id) | .offline_environments[] | "\(.variant):\(.flavor)"' \
	2>/dev/null || true)

SELECTED=()
for pair in "${RAW_ENVS[@]}"; do
	if [[ -n "${BUILDABLE[$pair]+_}" ]]; then
		SELECTED+=("$pair")
	else
		echo "  [skip] $pair — not marked build_image: true"
	fi
done

SELECTED_OFFLINE=()
for pair in "${RAW_OFFLINE[@]}"; do
	if [[ -n "${BUILDABLE[$pair]+_}" ]]; then
		SELECTED_OFFLINE+=("$pair")
	else
		echo "  [skip offline] $pair — not marked build_image: true"
	fi
done

if ((${#SELECTED[@]} == 0)); then
	echo "==> No buildable environments for de_iso_group '${DE_ID}'; nothing to do." >&2
	exit 0
fi

if ((${#SELECTED_OFFLINE[@]} == 0)); then
	SELECTED_OFFLINE=("${SELECTED[@]}")
fi

ISO_BASENAME="tuna-${DE_ID}"
echo "==> Building DE-grouped ISO '${ISO_BASENAME}'"
echo "    environments: ${SELECTED[*]}"
echo "    offline payloads: ${SELECTED_OFFLINE[*]}"

# ── Build the recipe ─────────────────────────────────────────────────────────
OUT_DIR=".build/iso-de-group/${ISO_BASENAME}"
mkdir -p "$OUT_DIR"
RECIPE_FILE="${OUT_DIR}/recipe.json"

ENVS_JSON="[]"
FIRST_REF=""
for pair in "${SELECTED[@]}"; do
	variant="${pair%%:*}"
	flavor="${pair##*:}"
	ref="$(tunaos_image_ref "$variant" "$flavor" "$REPO" "$flavor")"
	[[ -z "$FIRST_REF" ]] && FIRST_REF="$ref"
	if [[ "$REPO" == "local" ]]; then
		tunaos_import_to_root_storage "$ref"
	fi
	ENVS_JSON="$(jq -c \
		--arg id "${variant}-${flavor}" \
		--arg image "$ref" \
		--arg title "$(tunaos_flavor_title "$flavor") (${variant^})" \
		--arg desktop "$(tunaos_flavor_desktop "$flavor")" \
		'. + [{id: $id, image: $image, title: $title, desktop: $desktop, modes: ["live"]}]' \
		<<<"$ENVS_JSON")"
done

OFFLINE_PAYLOADS_JSON="[]"
for pair in "${SELECTED_OFFLINE[@]}"; do
	variant="${pair%%:*}"
	flavor="${pair##*:}"
	ref="$(tunaos_image_ref "$variant" "$flavor" "$REPO" "$flavor")"
	if [[ "$REPO" == "local" ]]; then
		tunaos_import_to_root_storage "$ref"
	fi
	OFFLINE_PAYLOADS_JSON="$(jq -c --arg image "$ref" '. + [$image]' <<<"$OFFLINE_PAYLOADS_JSON")"
done

jq -n \
	--arg media_name "$GROUP_TITLE" \
	--argjson envs "$ENVS_JSON" \
	--argjson offline "$OFFLINE_PAYLOADS_JSON" \
	'{
		media_name: $media_name,
		size: "35G",
		shared_store: { dedup: true, compression: "release" },
		bootable_environments: $envs,
		offline_payloads: $offline
	}' >"$RECIPE_FILE"

echo "==> Recipe:"
cat "$RECIPE_FILE"

# ── Build ────────────────────────────────────────────────────────────────────
ISO_OUT="${OUT_DIR}/${ISO_BASENAME}.iso"
echo "==> Building combined DE-grouped ISO with tacklebox..."
tunaos_run_tacklebox "$RECIPE_FILE" "$OUT_DIR" "$ISO_OUT"

chown_back() {
	[[ -n "${SUDO_USER:-}" ]] || return 0
	chown "${SUDO_UID:-$(id -u "$SUDO_USER")}:${SUDO_GID:-$(id -g "$SUDO_USER")}" "$1" 2>/dev/null || true
}
chown_back "$ISO_OUT"

# ── Report final size for comparison with variant-grouped approach ───────────
VERSION_ID=$(podman run --rm --security-opt label=disable "$FIRST_REF" \
	sh -c '. /usr/lib/os-release && echo "${VERSION_ID}"')
ARCH=$(podman run --rm --security-opt label=disable "$FIRST_REF" uname -m)

FINAL_ISO="${REPO_ROOT}/${ISO_BASENAME}-${VERSION_ID}-${ARCH}.iso"
cp "$ISO_OUT" "$FINAL_ISO"
chown_back "$FINAL_ISO"

ISO_SIZE_MB=$(du -m "$FINAL_ISO" | cut -f1)
echo ""
echo "==> Done!"
echo "    ISO:          ${FINAL_ISO}"
echo "    Size:         ${ISO_SIZE_MB} MB"
echo "    Environments: ${SELECTED[*]}"
echo ""
echo "Compare to variant-grouped approach:"
echo "    variant-community.iso would pack: ${#RAW_ENVS[@]} DEs for ONE variant"
echo "    this iso packs: ${#SELECTED[@]} variants for ONE DE"
