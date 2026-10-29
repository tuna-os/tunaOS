#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/build-config.sh
source "${SCRIPT_DIR}/lib/build-config.sh"
# shellcheck source=lib/publish-destination.sh
source "${SCRIPT_DIR}/lib/publish-destination.sh"

variant="${1:?usage: published-image-ref.sh <variant> <flavor-or-tag> [local|ghcr|registry]}"
tag="${2:?flavor or tag required}"
repo="${3:-ghcr}"
config="$(tunaos_build_config)"

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
ghcr)
	# "ghcr" is the published registry: [build.publish], else ghcr.io/<owner>.
	read -r registry namespace < <(tunaos_publish_destination "$config")
	printf '%s/%s/%s:%s\n' "$registry" "$namespace" "$name" "$tag"
	;;
registry) printf '%s/%s:%s\n' "${REGISTRY:-localhost:5000}" "$name" "$tag" ;;
*)
	echo "unknown repo: $repo" >&2
	exit 1
	;;
esac
