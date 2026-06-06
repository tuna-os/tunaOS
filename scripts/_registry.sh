#!/usr/bin/env bash
# _registry.sh — Registry prefix resolution for container image references.
#
# Sources registry-map.yaml and exports resolved image references. Every
# registry hostname and image tag can be overridden via environment variables.
#
# Environment variable overrides:
#   TUNA_REGISTRY_<key>     Override registry hostname (e.g. TUNA_REGISTRY_ghcr=mirror.example.com)
#   TUNA_IMAGE_PATH_<name>  Override image path (e.g. TUNA_IMAGE_PATH_common=myorg/common-fork)
#   TUNA_IMAGE_TAG_<name>   Override image tag (e.g. TUNA_IMAGE_TAG_common=v2.0)
#
# Usage:
#   source scripts/_registry.sh
#   common_ref=$(registry_ref common)         # → ghcr.io/projectbluefin/common:latest
#   common_ref=$(registry_ref common "@dig")  # → ghcr.io/projectbluefin/common@sha256:dig
#   akmods_base=$(registry_ref akmods)        # → ghcr.io/ublue-os (no tag — base path only)
#
#   # With overrides:
#   TUNA_REGISTRY_ghcr=mirror.example.com registry_ref common
#   # → mirror.example.com/projectbluefin/common:latest

set -euo pipefail

# Locate registry-map.yaml relative to the repo root.
_registry_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_registry_repo_root="$(cd "${_registry_script_dir}/.." && pwd)"
REGISTRY_MAP="${_registry_repo_root}/registry-map.yaml"

if [[ ! -f "${REGISTRY_MAP}" ]]; then
	echo "_registry.sh: FATAL: registry-map.yaml not found at ${REGISTRY_MAP}" >&2
	exit 1
fi

# Resolve a registry hostname for a given registry key.
# Applies TUNA_REGISTRY_<key> override if set.
#
# Usage: _registry_host ghcr  →  "ghcr.io" (or override)
_registry_host() {
	local key="$1"
	local override_var="TUNA_REGISTRY_${key}"
	if [[ -n "${!override_var:-}" ]]; then
		printf '%s' "${!override_var}"
	else
		yq -r ".registries.\"${key}\"" "${REGISTRY_MAP}"
	fi
}

# Resolve a full image reference for a logical image name.
#
# Usage:
#   registry_ref common            → ghcr.io/projectbluefin/common:latest
#   registry_ref common ":tag"     → ghcr.io/projectbluefin/common:tag
#   registry_ref common "@digest"  → ghcr.io/projectbluefin/common@digest
#   registry_ref akmods            → ghcr.io/ublue-os   (no tag for base paths)
#
# Override env vars (checked in order of precedence):
#   1. TUNA_IMAGE_PATH_<name> — full path override
#   2. TUNA_IMAGE_TAG_<name>  — tag override
#   3. TUNA_REGISTRY_<key>    — registry hostname override
registry_ref() {
	local name="$1"
	local tag_spec="${2:-}"

	# Resolve registry key and default path/tag from registry-map.yaml
	local registry_key
	registry_key="$(yq -r ".images.\"${name}\".registry" "${REGISTRY_MAP}")"
	if [[ -z "${registry_key}" || "${registry_key}" == "null" ]]; then
		echo "registry_ref: unknown image name '${name}'" >&2
		return 1
	fi

	local default_path
	default_path="$(yq -r ".images.\"${name}\".path" "${REGISTRY_MAP}")"

	local default_tag
	default_tag="$(yq -r ".images.\"${name}\".tag // \"\"" "${REGISTRY_MAP}")"

	# Apply overrides
	local path_override_var="TUNA_IMAGE_PATH_${name}"
	local path="${!path_override_var:-${default_path}}"

	local registry_host
	registry_host="$(_registry_host "${registry_key}")"

	local ref="${registry_host}/${path}"

	# Determine tag suffix
	if [[ -n "${tag_spec}" ]]; then
		# Explicit tag or digest passed by caller
		ref="${ref}${tag_spec}"
	elif [[ -n "${default_tag}" && "${default_tag}" != "null" ]]; then
		# Apply tag override if set
		local tag_override_var="TUNA_IMAGE_TAG_${name}"
		local tag="${!tag_override_var:-${default_tag}}"
		ref="${ref}:${tag}"
	fi
	# else: no tag (e.g. akmods base path)

	printf '%s' "${ref}"
}

# Export commonly-used image references so consumers don't need to call
# registry_ref repeatedly. Set only if not already overridden by caller.
if [[ -z "${COMMON_IMAGE:-}" ]]; then
	COMMON_IMAGE="$(registry_ref common)"
	export COMMON_IMAGE
fi
if [[ -z "${BREW_IMAGE:-}" ]]; then
	BREW_IMAGE="$(registry_ref brew)"
	export BREW_IMAGE
fi
if [[ -z "${BASE_IMAGE:-}" ]]; then
	BASE_IMAGE="$(registry_ref almalinux-bootc)"
	export BASE_IMAGE
fi
