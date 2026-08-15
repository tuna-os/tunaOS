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
total_unreached=0

{
	echo "$start"
	echo
	echo "_Generated from the latest completed main-branch build for each variant. A cell is green when its image was successfully promoted to the published tag._"
	echo
	echo "_\`failing\` means a run asserted the cell and it failed. \`not reached\` means no run ever got to it — an earlier job stopped it, so there is no result either way. They are counted separately on purpose: treating absence of evidence as evidence of failure is the thing [docs/MATRIX-STATUS.md](docs/MATRIX-STATUS.md) exists to prevent._"
	echo
	echo '| Variant | Green image cells | Latest run | Failing | Not reached |'
	echo '| :--- | ---: | :--- | :--- | :--- |'
} >"$tmp_table"

while IFS=$'\t' read -r variant emoji; do
	mapfile -t configured < <(yq -r ".variants[] | select(.id == \"$variant\") | .flavors[] | select(.build_image == true) | .id" "$config")
	count=${#configured[@]}
	total_cells=$((total_cells + count))

	# A cancelled run is a superseded run, not a broken build — rendering one
	# as ❌ is the misreading docs/MATRIX-STATUS.md calls out by name. Ask for
	# several and take the newest that actually concluded success or failure.
	run=$(gh run list \
		--repo "$repo" \
		--workflow "build-${variant}.yml" \
		--branch main \
		--status completed \
		--limit 10 \
		--json databaseId,conclusion,createdAt,url \
		--jq '[.[] | select(.conclusion == "success" or .conclusion == "failure")] | .[0:1]')

	if [[ $(jq 'length' <<<"$run") -eq 0 ]]; then
		printf '| %s `%s` | 0/%d | no completed run | — | all |\n' "$emoji" "$variant" "$count" >>"$tmp_table"
		total_unreached=$((total_unreached + count))
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
	unreached=()
	for flavor in "${configured[@]}"; do
		promotion=$(awk -F '\t' -v suffix="/ ${flavor} / Promote" \
			'index($1, suffix) == length($1) - length(suffix) + 1 { result=$2 } END { print result }' <<<"$promotions")
		# No Promote job in the run at all: the stage was skipped wholesale and
		# this flavor never built. GitHub collapses those into one placeholder
		# job, so the cell leaves no trace beyond its own absence.
		promotion=${promotion:-missing}
		case "$promotion" in
		success)
			green=$((green + 1))
			;;
		failure)
			failed+=("$flavor")
			;;
		*)
			# skipped | cancelled | missing — a gate stopped it, the run was
			# superseded, or the job never existed. None of these is a verdict
			# on the image.
			unreached+=("$flavor")
			;;
		esac
	done
	total_green=$((total_green + green))
	total_unreached=$((total_unreached + ${#unreached[@]}))

	if ((${#failed[@]} == 0)); then
		failed_text='—'
	else
		failed_text=$(
			IFS=', '
			echo "${failed[*]}"
		)
	fi
	if ((${#unreached[@]} == 0)); then
		unreached_text='—'
	else
		unreached_text=$(
			IFS=', '
			echo "${unreached[*]}"
		)
	fi
	icon='❌'
	[[ "$conclusion" == success ]] && icon='✅'
	printf '| %s `%s` | **%d/%d** | [%s %s](%s) | %s | %s |\n' \
		"$emoji" "$variant" "$green" "$count" "$icon" "$run_date" "$run_url" "$failed_text" "$unreached_text" >>"$tmp_table"
done < <(yq -r '.variants[] | [.id, .emoji] | @tsv' "$config")

percent=$((100 * total_green / total_cells))
total_failing=$((total_cells - total_green - total_unreached))
{
	echo
	echo "**Current image coverage: ${total_green}/${total_cells} cells (${percent}%).** Of the rest, ${total_failing} failed a run and ${total_unreached} were never reached. This is a point-in-time CI snapshot, not a support-tier promise."
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
