#!/usr/bin/env bash
# Read changed paths, one per line; succeed when a Tuna PR image input changed.
set -eu

while IFS= read -r path || [[ -n "$path" ]]; do
	case "$path" in
	.github/build-config.yml | .github/workflows/build-variant.yml | .github/workflows/reusable-build-image.yml | .github/actions/* | .github/scripts/* | Containerfile* | build_scripts/* | experiences/* | image-versions.yaml | manifests/desktops/tuna*.yaml | manifests/desktop-contracts/* | system_files/* | system_files_overrides/* | scripts/* | Justfile | just/* | tests/functional/* | tunaos.toml)
		printf 'Tuna image input changed: %s\n' "$path"
		exit 0
		;;
	esac
done

exit 1
