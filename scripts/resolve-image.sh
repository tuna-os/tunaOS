#!/usr/bin/env bash
# resolve-image.sh — Single entry point for all image reference lookups.
#
# Consolidates three sources of image metadata:
#   - .github/build-config.yml  (base_image per variant)
#   - image-versions.yaml       (digest pins for common/brew/zirconium)
#   - registry-map.yaml         (mirror overrides via _registry.sh)
#
# Usage:
#   ./scripts/resolve-image.sh <variant> <role>
#
# Roles:
#   base       — the OS base image for a variant (from build-config.yml)
#   common     — projectbluefin/common with pinned digest
#   brew       — ublue-os/brew with pinned digest
#   zirconium  — zirconium-dev/zirconium with pinned digest
#   utah-packages — projectbluefin/utah-packages (Hummingbird GNOME repo) with pinned digest
#   gnome50-el10-packages — tuna-os/tunaos-packages (EL10 GNOME 50 repo) with pinned digest
#   akmods     — akmods-nvidia-open registry base (with mirror support)
#
# Output: fully-qualified image reference (image@sha256:... or image:tag)

set -euo pipefail

VARIANT="${1:?Usage: resolve-image.sh <variant> <role>}"
ROLE="${2:?Usage: resolve-image.sh <variant> <role>}"
YQ="${YQ:-yq}"

# Source registry mirror support
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/_registry.sh" 2>/dev/null || true
# shellcheck source=lib/build-config.sh
source "${SCRIPT_DIR}/lib/build-config.sh"
BUILD_CONFIG="$(tunaos_build_config)"

case "${ROLE}" in
base)
	# Base image from build-config.yml
	$YQ -r ".variants[] | select(.id == \"${VARIANT}\") | .base_image" "$BUILD_CONFIG"
	;;
common)
	IMAGE="${COMMON_IMAGE:-ghcr.io/projectbluefin/common}"
	DIGEST=$($YQ -r '.images[] | select(.name == "common") | .digest' image-versions.yaml)
	# Strip any :tag from IMAGE since digest takes precedence
	echo "${IMAGE%%:*}@${DIGEST}"
	;;
brew)
	IMAGE="${BREW_IMAGE:-ghcr.io/ublue-os/brew}"
	DIGEST=$($YQ -r '.images[] | select(.name == "brew") | .digest' image-versions.yaml)
	echo "${IMAGE%%:*}@${DIGEST}"
	;;
zirconium)
	DIGEST=$($YQ -r '.images[] | select(.name == "zirconium") | .digest' image-versions.yaml)
	echo "ghcr.io/zirconium-dev/zirconium@${DIGEST}"
	;;
utah-packages)
	IMAGE="${UTAH_PACKAGES_IMAGE:-ghcr.io/projectbluefin/utah-packages}"
	DIGEST=$($YQ -r '.images[] | select(.name == "utah-packages") | .digest' image-versions.yaml)
	echo "${IMAGE%%:*}@${DIGEST}"
	;;
gnome50-el10-packages)
	IMAGE="${GNOME50_EL10_PACKAGES_IMAGE:-ghcr.io/tuna-os/tunaos-packages}"
	DIGEST=$($YQ -r '.images[] | select(.name == "gnome50-el10-packages") | .digest' image-versions.yaml)
	echo "${IMAGE%%:*}@${DIGEST}"
	;;
akmods)
	AKMODS_ORG=$($YQ -r ".variants[] | select(.id == \"${VARIANT}\") | .akmods // \"ublue-os\"" "$BUILD_CONFIG")
	registry_ref akmods 2>/dev/null || echo "ghcr.io/${AKMODS_ORG}"
	;;
*)
	echo "ERROR: unknown role '${ROLE}'. Valid: base, common, brew, zirconium, utah-packages, gnome50-el10-packages, akmods" >&2
	exit 1
	;;
esac
