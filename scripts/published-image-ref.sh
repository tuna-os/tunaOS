#!/usr/bin/env bash
set -euo pipefail

variant="${1:?usage: published-image-ref.sh <variant> <flavor-or-tag> [local|ghcr|registry]}"
tag="${2:?flavor or tag required}"
repo="${3:-ghcr}"
config="${TUNAOS_BUILD_CONFIG:-.github/build-config.yml}"

export VARIANT_ID="$variant"
name=$(yq -r '.variants[] | select(.id == strenv(VARIANT_ID)) | .publish_name // .id' "$config")
suffix=$(yq -r '.variants[] | select(.id == strenv(VARIANT_ID)) | .tag_suffix // ""' "$config")
if [[ -z "$name" || "$name" == null ]]; then
	echo "unknown variant: $variant" >&2
	exit 1
fi
if [[ -n "$suffix" && "$tag" != *-"$suffix" && "$tag" != *-"$suffix"-* ]]; then
	if [[ "$tag" == *-testing ]]; then
		tag="${tag%-testing}-${suffix}-testing"
	else
		tag="${tag}-${suffix}"
	fi
fi

case "$repo" in
local) printf 'localhost/%s:%s\n' "$variant" "$tag" ;;
ghcr) printf 'ghcr.io/%s/%s:%s\n' "${GITHUB_REPOSITORY_OWNER:-tuna-os}" "$name" "$tag" ;;
registry) printf '%s/%s:%s\n' "${REGISTRY:-localhost:5000}" "$name" "$tag" ;;
*)
	echo "unknown repo: $repo" >&2
	exit 1
	;;
esac
