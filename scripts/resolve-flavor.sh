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
#   OVERLAY_TYPE     — hwe, nvidia, or empty
#   PARENT_FLAVOR    — parent image tag (for chained builds)

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

CONTAINERFILE="Containerfile"
ENABLE_HWE="0"
ENABLE_NVIDIA="0"
OVERLAY_TYPE=""
PARENT_FLAVOR=""
DESKTOP_FLAVOR="${FLAVOR}"

# RFC 010: grouper (Ubuntu) uses Containerfile.ubuntu
if [[ "${VARIANT}" == "grouper" ]]; then
    CONTAINERFILE="Containerfile.ubuntu"
fi

# Debian variants use Containerfile.debian
if [[ "${VARIANT}" == "flounder" || "${VARIANT}" == "flounder-sid" ]]; then
    CONTAINERFILE="Containerfile.debian"
fi

# Arch-based variants use Containerfile.arch
if [[ "${VARIANT}" == "marlin" || "${VARIANT}" == "wahoo" ]]; then
    CONTAINERFILE="Containerfile.arch"
fi

if [[ "${FLAVOR}" == "base" ]]; then
    DESKTOP_FLAVOR="base-no-de"
    # grouper's base-no-de is intentionally pre-bootcify
    if [[ "${VARIANT}" == "grouper" ]]; then DESKTOP_FLAVOR="base"; fi
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
PARENT_FLAVOR="${PARENT_FLAVOR}"
FLAVOR="${FLAVOR}"
EOF
