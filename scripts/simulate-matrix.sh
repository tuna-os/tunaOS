#!/usr/bin/env bash
set -euo pipefail

# This script simulates the GitHub Actions build matrix based on build-config.yml

echo "Simulated GitHub Actions Matrix (Dry Run):"
echo "=========================================="

yq -o=json '.variants[] | {"variant": .id, "description": .description, "platforms": .platforms, "flavors": [.flavors[] | select(.build_image == true) | .id]}' .github/build-config.yml | jq -c '.' | while read -r line; do
	VARIANT=$(echo "$line" | jq -r '.variant')
	DESC=$(echo "$line" | jq -r '.description')
	PLATFORMS=$(echo "$line" | jq -r '.platforms | join(", ")')
	echo ""
	echo "Variant: $VARIANT ($DESC)"
	echo "Platforms: $PLATFORMS"
	echo "Pipeline Execution Simulation:"
	echo "------------------------------"

	# We will simulate the build commands that would be executed in sequence
	echo "$line" | jq -r '.flavors[]' | while read -r FLAVOR; do
		LOCAL_IMAGE_REF="localhost/${VARIANT}:${FLAVOR}"
		GHCR_REF="ghcr.io/${GITHUB_REPOSITORY_OWNER:-tuna-os}/${VARIANT}:${FLAVOR}"

		echo "Flavor: $FLAVOR"
		for platform in $(echo "$line" | jq -r '.platforms[]'); do
			echo "  --> just build \"$VARIANT\" \"$FLAVOR\" \"$platform\" 1 \"latest\""
		done

		echo "  --> just chunkify \"$LOCAL_IMAGE_REF\""
		echo "  --> podman image tag \"$LOCAL_IMAGE_REF\" \"$GHCR_REF\""
		echo "  --> podman push \"$GHCR_REF\" (to registry)"
		echo ""
	done
done
echo "=========================================="
