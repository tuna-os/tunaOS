#!/usr/bin/env bash
# Resolve the provider-neutral build contract through one compatibility seam.
# Consumers should use TUNAOS_BUILD_CONFIG rather than depending on its current
# GitHub-specific storage location.

tunaos_build_config() {
	local library_dir repo_root config
	library_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
	repo_root="$(cd "${library_dir}/../.." && pwd)"
	if [[ -n "${TUNAOS_BUILD_CONFIG:-}" ]]; then
		config="$TUNAOS_BUILD_CONFIG"
	else
		config="$(python3 "${repo_root}/scripts/config.py" generate --root "$repo_root")" || return 1
	fi

	if [[ ! -f "$config" ]]; then
		echo "ERROR: build config not found: ${config}" >&2
		return 1
	fi
	printf '%s\n' "$config"
}
