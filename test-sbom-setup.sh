#!/usr/bin/env bash
# Test script to verify SBOM setup for changelog generation

set -euo pipefail

echo "=== Testing SBOM Setup for TunaOS Changelog ==="
echo ""

# Check if oras is installed
if ! command -v oras &>/dev/null; then
	echo "❌ oras not found. Installing..."
	curl -o oras.tar.gz -sSL https://github.com/oras-project/oras/releases/download/v1.2.4/oras_1.2.4_linux_amd64.tar.gz
	sudo tar -C /usr/local/bin -xzf oras.tar.gz oras
	rm oras.tar.gz
fi
echo "✅ oras is installed"

# Check if cosign is installed
if ! command -v cosign &>/dev/null; then
	echo "❌ cosign not found. Installing..."
	curl -o cosign.installer.sh -sSL https://raw.githubusercontent.com/sigstore/cosign/main/install.sh
	sudo bash cosign.installer.sh
	rm cosign.installer.sh
fi
echo "✅ cosign is installed"

# Check if skopeo is installed
if ! command -v skopeo &>/dev/null; then
	echo "❌ skopeo not found. Installing..."
	sudo dnf install -y skopeo
fi
echo "✅ skopeo is installed"

echo ""
echo "=== Checking SBOM Referrers for TunaOS Images ==="
echo ""

# Check each image
for image in yellowfin albacore skipjack; do
	echo "--- $image ---"

	# Get latest tag
	LATEST_TAG=$(skopeo inspect "docker://ghcr.io/tuna-os/$image:latest" --format '{{index .RepoTags 0}}' 2>/dev/null || echo "latest")

	# Get digest
	DIGEST=$(skopeo inspect "docker://ghcr.io/tuna-os/$image:latest" --format '{{.Digest}}' 2>/dev/null)

	if [ -z "$DIGEST" ]; then
		echo "⚠️  Could not get digest for $image:latest"
		continue
	fi

	echo "Latest tag: $LATEST_TAG"
	echo "Digest: $DIGEST"

	# Check for SBOM referrers
	echo "Checking for SBOM referrers..."
	if oras discover --artifact-type application/vnd.spdx+json --format json "ghcr.io/tuna-os/$image@$DIGEST" 2>/dev/null | grep -q referrers; then
		echo "✅ SBOM referrers found!"
		oras discover --artifact-type application/vnd.spdx+json --format json "ghcr.io/tuna-os/$image@$DIGEST" 2>/dev/null | jq .
	else
		echo "❌ No SBOM referrers found for $image:$LATEST_TAG"
	fi
	echo ""
done

echo "=== Summary ==="
echo "You need at least 2 builds with SBOMs attached to generate a changelog."
echo "The changelog action will automatically discover and compare the 2 most recent SBOM-bearing tags."
