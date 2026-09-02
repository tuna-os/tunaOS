#!/usr/bin/env bash
set -euo pipefail

# Render the "sibling images" table for the README build matrix: bootc images
# in the tunaOS family that are BUILT ELSEWHERE (BuildStream projects on
# freedesktop-sdk -- tromso, xfce-linux) and so never enter this repo's
# variant matrix or its green criteria. They are products, not package
# sources: whole OS images built from one SDK, which is exactly why their
# objects cannot be repackaged for the distro variants here
# (tunaos-packages docs/experiments/tideforge-universal-intermediate.md).
#
# Reads `sibling_images:` from build-config.yml and each repo's latest
# completed main-branch run of its scheduled build workflow. Fetch failures
# render as ⬜ (not fetched), never as a pass or a fail, and never stop the
# README refresh: the variant table above this one is the load-bearing part.
#
# Requires: gh, yq. Usage: sibling-images-status.sh [build-config.yml]

config="${1:-.github/build-config.yml}"

count=$(yq -r '.sibling_images | length // 0' "$config")
if ((count == 0)); then
	exit 0
fi

echo
echo "**Sibling images, built in their own repositories.** These are TunaOS-family bootc images built with BuildStream on freedesktop-sdk rather than from a distribution's packages, so they have no cells in the matrix above and are not scored by \`green-criteria.yml\`; each repository runs its own build, live-ISO, plain-install and LUKS-install checks. Status is that repository's latest completed main-branch build."
echo
echo '| Image | Built by | Desktop | Latest main build |'
echo '| :--- | :--- | :--- | :--- |'

for ((i = 0; i < count; i++)); do
	id=$(yq -r ".sibling_images[$i].id" "$config")
	emoji=$(yq -r ".sibling_images[$i].emoji" "$config")
	image=$(yq -r ".sibling_images[$i].image" "$config")
	repo=$(yq -r ".sibling_images[$i].repo" "$config")
	workflow=$(yq -r ".sibling_images[$i].workflow" "$config")
	desktops=$(yq -r ".sibling_images[$i].desktops | join(\", \")" "$config")

	status='⬜ not fetched'
	# Newest run that actually concluded; a cancelled or in-flight run is not
	# a verdict (same rule as update-build-status.sh, tunaOS#1730).
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
	printf '| %s `%s` | [%s](https://github.com/%s) | %s | %s |\n' \
		"$emoji" "$image" "$id" "$repo" "$desktops" "$status"
done
