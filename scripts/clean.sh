#!/usr/bin/env bash
# Clean build artifacts and local container images.
#
# Usage: scripts/clean.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

YQ="${yq:-$(command -v yq 2>/dev/null || echo /home/linuxbrew/.linuxbrew/bin/yq)}"

echo "Cleaning up build artifacts and images..."
echo "Note: Preserving .rpm-cache for faster rebuilds. Use 'just clean-cache' to remove."
rm -rf .build-logs
sudo rm -rf .build/*
rm -f out.ociarchive
echo "Removing local podman images for all variants and flavors..."
readarray -t VARIANTS < <("$YQ" -r '.variants[].id' .github/build-config.yml 2>/dev/null || printf '%s\n' yellowfin albacore bonito skipjack redfin)
for variant in "${VARIANTS[@]}"; do
	readarray -t FLAVORS < <("$YQ" -r ".variants[] | select(.id == \"$variant\") | .flavors[].id" .github/build-config.yml 2>/dev/null || true)
	for flavor in "${FLAVORS[@]}"; do
		podman rmi -f "localhost/${variant}:${flavor}" 2>/dev/null || true
		sudo podman rmi -f "localhost/${variant}:${flavor}" 2>/dev/null || true
	done
done
