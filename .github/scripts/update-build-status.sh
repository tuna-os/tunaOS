#!/usr/bin/env bash
set -euo pipefail

# Regenerate the README build-matrix snapshot from build-config.yml and the
# latest completed main-branch run of each variant workflow.
# Requires: gh, jq, yq. GITHUB_TOKEN must be able to read Actions metadata.

repo="${GITHUB_REPOSITORY:-tuna-os/tunaOS}"
config="${1:-.github/build-config.yml}"
readme="${2:-README.md}"
start='<!-- build-status:start -->'
end='<!-- build-status:end -->'
tmp_table=$(mktemp)
tmp_readme=$(mktemp)
trap 'rm -f "$tmp_table" "$tmp_readme"' EXIT

total_green=0
total_cells=0

{
	echo "$start"
	echo
  echo "_Generated from the latest completed main-branch build for each variant. A cell is green when its image was successfully promoted to the published tag._"
	echo
	echo '| Variant | Green image cells | Latest run | Blocked or failing tags |'
	echo '| :--- | ---: | :--- | :--- |'
} >"$tmp_table"

while IFS=$'\t' read -r variant emoji; do
	mapfile -t configured < <(yq -r ".variants[] | select(.id == \"$variant\") | .flavors[] | select(.build_image == true) | .id" "$config")
	count=${#configured[@]}
	total_cells=$((total_cells + count))

	run=$(gh run list \
		--repo "$repo" \
		--workflow "build-${variant}.yml" \
		--branch main \
		--status completed \
		--limit 1 \
		--json databaseId,conclusion,createdAt,url)

	if [[ $(jq 'length' <<<"$run") -eq 0 ]]; then
		printf '| %s `%s` | 0/%d | no completed run | all |\n' "$emoji" "$variant" "$count" >>"$tmp_table"
		continue
	fi

	run_id=$(jq -r '.[0].databaseId' <<<"$run")
	conclusion=$(jq -r '.[0].conclusion' <<<"$run")
	run_url=$(jq -r '.[0].url' <<<"$run")
	run_date=$(jq -r '.[0].createdAt[0:10]' <<<"$run")
  promotions=$(gh api --paginate "repos/${repo}/actions/runs/${run_id}/jobs?per_page=100" \
    --jq '.jobs[] | select(.name | endswith(" / Promote")) | [.name, .conclusion] | @tsv')

	green=0
	failed=()
	for flavor in "${configured[@]}"; do
    promotion=$(awk -F '\t' -v suffix="/ ${flavor} / Promote" \
      'index($1, suffix) == length($1) - length(suffix) + 1 { result=$2 } END { print result }' <<<"$promotions")
    promotion=${promotion:-missing}
    if [[ "$promotion" == success ]]; then
			green=$((green + 1))
		else
			failed+=("$flavor")
		fi
	done
	total_green=$((total_green + green))

	if ((${#failed[@]} == 0)); then
		failed_text='—'
	else
		failed_text=$(
			IFS=', '
			echo "${failed[*]}"
		)
	fi
	icon='❌'
	[[ "$conclusion" == success ]] && icon='✅'
	printf '| %s `%s` | **%d/%d** | [%s %s](%s) | %s |\n' \
		"$emoji" "$variant" "$green" "$count" "$icon" "$run_date" "$run_url" "$failed_text" >>"$tmp_table"
done < <(yq -r '.variants[] | [.id, .emoji] | @tsv' "$config")

percent=$((100 * total_green / total_cells))
{
	echo
	echo "**Current image coverage: ${total_green}/${total_cells} cells (${percent}%).** This is a point-in-time CI snapshot, not a support-tier promise."
	echo
	echo "$end"
} >>"$tmp_table"

awk -v replacement="$tmp_table" -v start="$start" -v end="$end" '
  $0 == start {
    while ((getline line < replacement) > 0) print line
    skipping = 1
    next
  }
  $0 == end { skipping = 0; next }
  !skipping { print }
' "$readme" >"$tmp_readme"
mv "$tmp_readme" "$readme"
