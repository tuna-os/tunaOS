#!/usr/bin/env bash
# Audit the NVIDIA release surface without changing releases or assets.
# A red result is intentional: it makes a missing downloadable artifact
# visible to the release owners instead of allowing the catalog to look green.
set -euo pipefail

repo="${NVIDIA_AUDIT_REPO:-${GITHUB_REPOSITORY:-tuna-os/tunaos}}"
minimum="${NVIDIA_MIN_ASSETS:-1}"

command -v gh >/dev/null || {
	echo "FAIL: gh is required to inspect release assets" >&2
	exit 1
}
command -v jq >/dev/null || {
	echo "FAIL: jq is required to inspect release assets" >&2
	exit 1
}

case "$minimum" in
	''|*[!0-9]*)
		echo "FAIL: NVIDIA_MIN_ASSETS must be a non-negative integer" >&2
		exit 1
		;;
esac

flavors=(
	gnome-nvidia
	gnome50-nvidia
	xfce-nvidia
	niri-nvidia
	cosmic-nvidia
	kde-nvidia
)

fail=0
for flavor in "${flavors[@]}"; do
	release=$(GH_TOKEN="${GH_TOKEN:-}" gh api --paginate --slurp \
		"repos/$repo/releases?per_page=100" \
		| jq -c --arg prefix "$flavor-" \
		'add | map(select(.tag_name | startswith($prefix))) | sort_by(.published_at) | last // empty')

	if [ -z "$release" ]; then
		echo "MISSING $flavor: no GitHub release found"
	fail=1
		continue
	fi

	tag=$(jq -r '.tag_name' <<<"$release")
	assets=$(jq '.assets | length' <<<"$release")
	echo "$flavor: $tag ($assets asset(s))"
	if (( assets < minimum )); then
		echo "FAIL $flavor: latest release has fewer than $minimum asset(s)" >&2
		fail=1
	fi
done

if (( fail )); then
	echo "NVIDIA RELEASE ASSET AUDIT FAILED: restore downloadable assets for every NVIDIA edition" >&2
	exit 1
fi

echo "NVIDIA RELEASE ASSET AUDIT PASSED"
