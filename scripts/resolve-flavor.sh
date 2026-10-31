#!/usr/bin/env bash
# resolve-flavor.sh — Resolve a build flavor into its constituent parts.
#
# Extracts the complex flavor-resolution logic from the Justfile into a
# testable, standalone script. Outputs key=value pairs to stdout that the
# caller can eval or source.
#
# Usage:
#   eval "$(./scripts/resolve-flavor.sh <variant> <flavor> [is_ci])"
#
# Output variables:
#   CONTAINERFILE    — which Containerfile to use
#   BASE_FOR_BUILD   — the image to build FROM (empty = use get-base-image.sh)
#   DESKTOP_FLAVOR   — the --target stage name
#   ENABLE_HWE       — 0 or 1
#   ENABLE_NVIDIA    — 0 or 1
#   OVERLAY_TYPE     — hwe, nvidia, cachyos, asahi, hardware, or empty
#   ENABLE_ASAHI     — 0 or 1 (grouper full-build asahi path)
#   PARENT_FLAVOR    — parent image tag (for chained builds)
#   HARDWARE_PROFILE — [hardware.<id>] profile id for OVERLAY_TYPE=hardware
#
# Hardware flavors (`hardware = "<id>"` in tunaos.toml) are looked up in the
# generated build_scripts/lib/hardware-profiles.json
# (TUNAOS_HARDWARE_PROFILES overrides the path), never by flavor name.

set -euo pipefail

VARIANT="${1:?Usage: resolve-flavor.sh <variant> <flavor> [is_ci]}"
FLAVOR="${2:?Usage: resolve-flavor.sh <variant> <flavor> [is_ci]}"
# shellcheck disable=SC2034 # IS_CI reserved for future CI-specific resolution
IS_CI="${3:-0}"

# Normalize legacy shorthand names
case "${FLAVOR}" in
"hwe") FLAVOR="gnome-hwe" ;;
"nvidia") FLAVOR="gnome-nvidia" ;;
"gdx-hwe") FLAVOR="gnome-nvidia-hwe" ;;
esac

CONTAINERFILE="Containerfile.el10"
ENABLE_HWE="0"
ENABLE_NVIDIA="0"
ENABLE_ASAHI="0"
OVERLAY_TYPE=""
PARENT_FLAVOR=""
DESKTOP_FLAVOR="${FLAVOR}"
HARDWARE_PROFILE=""

HARDWARE_PROFILES="${TUNAOS_HARDWARE_PROFILES:-$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../build_scripts/lib/hardware-profiles.json}"
if [[ -f "${HARDWARE_PROFILES}" ]]; then
	if ! command -v jq >/dev/null 2>&1; then
		echo "ERROR: resolve-flavor.sh needs jq to read ${HARDWARE_PROFILES}" >&2
		exit 1
	fi
	hardware_entry="$(jq -r --arg v "${VARIANT}" --arg f "${FLAVOR}" \
		'.flavors[$v][$f] // empty | "\(.hardware) \(.parent)"' "${HARDWARE_PROFILES}")"
	if [[ -n "${hardware_entry}" ]]; then
		read -r HARDWARE_PROFILE PARENT_FLAVOR <<<"${hardware_entry}"
	fi
fi

# RFC 010: grouper (Ubuntu) uses Containerfile.ubuntu
# Sailfin uses Containerfile.opensuse
if [[ "${VARIANT}" == "sailfin" ]]; then
	CONTAINERFILE="Containerfile.opensuse"
fi

# Guppy uses Containerfile.gentoo
if [[ "${VARIANT}" == "guppy" ]]; then
	CONTAINERFILE="Containerfile.gentoo"
fi

# grouper (Ubuntu resolute) and gurnard (Ubuntu noble) both build from
# Containerfile.ubuntu. gurnard was never added here, so it fell through to the
# Containerfile.el10 default and every build died — "Unknown variant: gurnard"
# (#1014). It is a separate variant rather than a grouper flavour because
# Pantheon's PPA publishes for noble and jammy only, nothing for resolute
# (see the header of manifests/desktops/pantheon.yaml).
if [[ "${VARIANT}" == "grouper" || "${VARIANT}" == "gurnard" ]]; then
	CONTAINERFILE="Containerfile.ubuntu"
fi

# Debian variants use Containerfile.debian
if [[ "${VARIANT}" == "flounder" || "${VARIANT}" == "flounder-sid" ]]; then
	CONTAINERFILE="Containerfile.debian"
fi

# Arch-based variants use Containerfile.arch
if [[ "${VARIANT}" == "marlin" ]]; then
	CONTAINERFILE="Containerfile.arch"
fi

if [[ -n "${HARDWARE_PROFILE}" ]]; then
	# Generic hardware profile on its declared parent flavor
	# (build_scripts/overlay/hardware-profile.sh).
	CONTAINERFILE="Containerfile.overlay"
	OVERLAY_TYPE="hardware"
	DESKTOP_FLAVOR="desktop"
elif [[ "${VARIANT}" == "grouper" && "${FLAVOR}" == *"-asahi" ]]; then
	# grouper's kernel decision happens in the base stage of Containerfile.ubuntu,
	# so the asahi flavor is a full (stage-1 style) build with ENABLE_ASAHI=1,
	# not an overlay on the stock-kernel base. aarch64 only.
	CONTAINERFILE="Containerfile.ubuntu"
	ENABLE_ASAHI="1"
	DESKTOP_FLAVOR="${FLAVOR%-asahi}"
elif [[ "${VARIANT}" != "grouper" && "${FLAVOR}" == *"-asahi" ]]; then
	# Apple Silicon overlay on a DE image (build_scripts/overlay/asahi.sh);
	# aarch64 only — the overlay hard-fails on other arches.
	CONTAINERFILE="Containerfile.overlay"
	OVERLAY_TYPE="asahi"
	DESKTOP_FLAVOR="desktop"
	PARENT_FLAVOR="${FLAVOR%-asahi}"
elif [[ "${VARIANT}" == "marlin" && "${FLAVOR}" == *"-cachyos" ]]; then
	CONTAINERFILE="Containerfile.overlay"
	OVERLAY_TYPE="cachyos"
	DESKTOP_FLAVOR="desktop"
	PARENT_FLAVOR="${FLAVOR%-cachyos}"
elif [[ "${FLAVOR}" == "base" ]]; then
	DESKTOP_FLAVOR="base-no-de"
	# grouper's base-no-de is intentionally pre-bootcify. gurnard shares
	# Containerfile.ubuntu, so it shares that stage layout too.
	if [[ "${VARIANT}" == "grouper" || "${VARIANT}" == "gurnard" ]]; then DESKTOP_FLAVOR="base"; fi
elif [[ "${FLAVOR}" == "base-hwe" ]]; then
	CONTAINERFILE="Containerfile.overlay"
	OVERLAY_TYPE="hwe"
	ENABLE_HWE="1"
	DESKTOP_FLAVOR="desktop"
	PARENT_FLAVOR="base"
elif [[ "${FLAVOR}" == "base-nvidia" ]]; then
	CONTAINERFILE="Containerfile.overlay"
	OVERLAY_TYPE="nvidia"
	ENABLE_NVIDIA="1"
	DESKTOP_FLAVOR="desktop"
	PARENT_FLAVOR="base"
elif [[ "${VARIANT}" != "grouper" && "${FLAVOR}" == *"-nvidia-hwe" ]]; then
	DESKTOP_FLAVOR="desktop"
	CONTAINERFILE="Containerfile.overlay"
	OVERLAY_TYPE="nvidia"
	ENABLE_NVIDIA="1"
	ENABLE_HWE="1"
	PARENT_FLAVOR="${FLAVOR%-nvidia-hwe}-hwe"
elif [[ "${VARIANT}" != "grouper" && "${FLAVOR}" == *"-hwe" ]]; then
	DESKTOP_FLAVOR="desktop"
	CONTAINERFILE="Containerfile.overlay"
	OVERLAY_TYPE="hwe"
	ENABLE_HWE="1"
	PARENT_FLAVOR="${FLAVOR%-hwe}"
elif [[ "${VARIANT}" != "grouper" && "${FLAVOR}" == *"-nvidia" ]]; then
	DESKTOP_FLAVOR="desktop"
	CONTAINERFILE="Containerfile.overlay"
	OVERLAY_TYPE="nvidia"
	ENABLE_NVIDIA="1"
	PARENT_FLAVOR="${FLAVOR%-nvidia}"
else
	DESKTOP_FLAVOR="${FLAVOR}"
fi

# Emit structured output
cat <<EOF
CONTAINERFILE="${CONTAINERFILE}"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR}"
ENABLE_HWE="${ENABLE_HWE}"
ENABLE_NVIDIA="${ENABLE_NVIDIA}"
OVERLAY_TYPE="${OVERLAY_TYPE}"
ENABLE_ASAHI="${ENABLE_ASAHI}"
PARENT_FLAVOR="${PARENT_FLAVOR}"
HARDWARE_PROFILE="${HARDWARE_PROFILE}"
FLAVOR="${FLAVOR}"
EOF
