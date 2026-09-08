#!/usr/bin/env bash
# Resolve TunaOS image names without importing ISO build infrastructure.
# This library intentionally has no source-time side effects.

tunaos_image_ref() {
	local variant="${1:?variant required}"
	local flavor="${2:-gnome}"
	local repo="${3:-local}"
	local tag="${4:-${flavor}}"

	if [[ "$variant" == *":"* || "$variant" == *"/"* ]]; then
		echo "$variant"
		return
	fi

	local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
	case "$repo" in
	local)
		echo "localhost/${variant}:${tag}"
		;;
	ghcr)
		GITHUB_REPOSITORY_OWNER="$owner" bash ./scripts/published-image-ref.sh "$variant" "$tag" ghcr
		;;
	registry)
		bash ./scripts/published-image-ref.sh "$variant" "$tag" registry
		;;
	*)
		echo "ERROR: unknown repo '${repo}' (expected: local | ghcr | registry)" >&2
		return 1
		;;
	esac
}
