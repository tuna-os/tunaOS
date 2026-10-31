#!/usr/bin/env bash
# Resolve TunaOS image names without importing ISO build infrastructure.
# This library intentionally has no source-time side effects.

tunaos_image_ref() {
	local variant="${1:?variant required}"
	local flavor="${2:-gnome}"
	local repo="${3:-local}"
	local tag="${4:-${flavor}}"
	local allow_override="${5:-1}"
	if [[ "$allow_override" == "1" && "$repo" == "ghcr" && -n "${TUNAOS_IMAGE_REF:-}" ]]; then
		echo "$TUNAOS_IMAGE_REF"
		return
	fi
	if [[ "$variant" == *":"* || "$variant" == *"/"* ]]; then
		echo "$variant"
		return
	fi

	case "$repo" in
	local)
		echo "localhost/${variant}:${tag}"
		;;
	ghcr)
		bash ./scripts/published-image-ref.sh "$variant" "$tag" ghcr
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
