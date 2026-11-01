#!/usr/bin/env bash
set -euo pipefail

# Render the BuildStream image family in the README image matrix. These
# independent bootc projects are products, not package sources, and remain
# outside the distro × desktop cell totals and their green criteria.
#
# Reads `sibling_images:` from the primary TunaOS config. Published OCI images
# report their latest conclusive main-branch scheduled build. A local-only
# BuildStream target is listed with its declared status and is never queried
# as if it were an image build. Fetch failures render ⬜, never a verdict.
#
# Requires: gh, yq, jq. Usage: sibling-images-status.sh [generated config]

if [[ -n "${1:-}" ]]; then
	config="$1"
else
	source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib/build-config.sh"
	config="$(tunaos_build_config)" || exit 1
fi

count=$(yq -r '.sibling_images | length // 0' "$config")
if ((count == 0)); then
	exit 0
fi

echo
echo "**BuildStream image family.** These TunaOS products use independent BuildStream projects and release pipelines. They are part of this image matrix, but remain separate from the distro × desktop cell counts and their green criteria. Published OCI references show the latest conclusive main-branch build. Athens is experimental and local-only: CI checks its graph, but there is no published image build."
echo
echo '| Brand | Image or target | Project | Desktop | Availability | Latest main build |'
echo '| :--- | :--- | :--- | :--- | :--- | :--- |'

for ((i = 0; i < count; i++)); do
	id=$(yq -r ".sibling_images[$i].id" "$config")
	mark=$(yq -r ".sibling_images[$i].mark // \"\"" "$config")
	image=$(yq -r ".sibling_images[$i].image // \"\"" "$config")
	target=$(yq -r ".sibling_images[$i].target // \"\"" "$config")
	repo=$(yq -r ".sibling_images[$i].repo" "$config")
	workflow=$(yq -r ".sibling_images[$i].workflow // \"\"" "$config")
	desktops=$(yq -r ".sibling_images[$i].desktops | join(\", \")" "$config")
	availability=$(yq -r ".sibling_images[$i].availability // \"Status not declared\"" "$config")

	if [[ -n "$mark" ]]; then
		brand="<img width=\"28\" alt=\"\" src=\"$mark\" />"
	else
		brand=''
	fi

	if [[ -n "$image" ]]; then
		output="\`$image\`"
		status='⬜ not fetched'
		# Newest run that actually concluded; a cancelled or in-flight run is
		# not a verdict (same rule as update-build-status.sh, tunaOS#1730).
		if runs=$(gh run list --repo "$repo" --workflow "$workflow" --branch main \
			--limit 10 --json databaseId,conclusion,createdAt,url,status 2>/dev/null); then
			line=$(jq -r '[.[] | select(.status == "completed" and (.conclusion == "success" or .conclusion == "failure"))][0] | select(. != null) | "\(.conclusion)\t\(.createdAt[:10])\t\(.url)"' <<<"$runs" 2>/dev/null || true)
			if [[ -n "$line" ]]; then
				IFS=$'\t' read -r conclusion date url <<<"$line"
				case "$conclusion" in
				success) icon='✅' ;;
				failure) icon='❌' ;;
				*) icon='⬜' ;;
				esac
				status="[${icon} ${date}](${url})"
			fi
		fi
	else
		output="\`$target\` (local-only)"
		status='— (graph checks only; no image build)'
	fi

	printf '| %s | %s | [%s](https://github.com/%s) | %s | %s | %s |\n' \
		"$brand" "$output" "$id" "$repo" "$desktops" "$availability" "$status"
done
