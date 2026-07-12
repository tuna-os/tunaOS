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

case "${ROLE}" in
base)
	# Base image from build-config.yml
	$YQ -r ".variants[] | select(.id == \"${VARIANT}\") | .base_image" .github/build-config.yml
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
akmods)
	AKMODS_ORG=$($YQ -r ".variants[] | select(.id == \"${VARIANT}\") | .akmods // \"ublue-os\"" .github/build-config.yml)
	registry_ref akmods 2>/dev/null || echo "ghcr.io/${AKMODS_ORG}"
	;;
*)
	echo "ERROR: unknown role '${ROLE}'. Valid: base, common, brew, zirconium, akmods" >&2
	exit 1
	;;
esac
