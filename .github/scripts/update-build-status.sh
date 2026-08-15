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

# Empty list renders as an em dash rather than a blank cell.
join_or_dash() {
	if (($# == 0)); then
		echo '—'
	else
		local IFS=', '
		echo "$*"
	fi
}

{
	echo "$start"
	echo
	echo "_Generated from the latest conclusive main-branch build for each variant (cancelled runs are skipped over). A cell is green when its image was successfully promoted to the published tag; **failing** means a job ran and failed; **not reached** means no job asserted the cell at all, usually because an earlier stage stopped it._"
	echo
	echo '| Variant | Green image cells | Latest run | Failing | Not reached |'
	echo '| :--- | ---: | :--- | :--- | :--- |'
} >"$tmp_table"

while IFS=$'\t' read -r variant emoji; do
	mapfile -t configured < <(yq -r ".variants[] | select(.id == \"$variant\") | .flavors[] | select(.build_image == true) | .id" "$config")
	count=${#configured[@]}
	total_cells=$((total_cells + count))

	# --status completed includes cancelled runs, and a cancelled run is not a
	# verdict on anything: docs/MATRIX-STATUS.md lists exactly this under
	# "Failures that look like successes" -- "a superseded run is not a broken
	# build". Fetch a short window and prefer the newest run that actually
	# concluded success or failure, so one cancellation does not blank a
	# variant's whole row (tunaOS#1730).
	runs=$(gh run list \
		--repo "$repo" \
		--workflow "build-${variant}.yml" \
		--branch main \
		--status completed \
		--limit 10 \
		--json databaseId,conclusion,createdAt,url)

	if [[ $(jq 'length' <<<"$runs") -eq 0 ]]; then
		printf '| %s `%s` | 0/%d | no completed run | — | all |\n' "$emoji" "$variant" "$count" >>"$tmp_table"
		total_unreached=$((total_unreached + count))
		continue
	fi

	# First conclusive run, else fall back to the newest so the row still
	# reports something and says why it is not conclusive.
	run=$(jq -c '[.[] | select(.conclusion == "success" or .conclusion == "failure")][0] // .[0]' <<<"$runs")
	run_id=$(jq -r '.databaseId' <<<"$run")
	conclusion=$(jq -r '.conclusion' <<<"$run")
	run_url=$(jq -r '.url' <<<"$run")
	run_date=$(jq -r '.createdAt[0:10]' <<<"$run")
	promotions=$(gh api --paginate "repos/${repo}/actions/runs/${run_id}/jobs?per_page=100" \
		--jq '.jobs[] | select(.name | endswith(" / Promote")) | [.name, .conclusion] | @tsv')

	# Three outcomes, not two. A cell only counts as FAILING when a job ran and
	# said so; "no Promote job existed" and "an upstream job stopped it" are
	# absence of evidence, and reporting them as failures is the conflation
	# docs/MATRIX-STATUS.md exists to prevent (tunaOS#1730). On 2026-08-14, 14
	# flavors across sailfin/marlin/flounder/gurnard produced no job at all --
	# their stage-2 group never ran because the base manifest failed first
	# (tunaOS#1729) -- and the table called every one of them blocked or
	# failing.
	green=0
	failing=()
	unreached=()
	for flavor in "${configured[@]}"; do
		promotion=$(awk -F '\t' -v suffix="/ ${flavor} / Promote" \
			'index($1, suffix) == length($1) - length(suffix) + 1 { result=$2 } END { print result }' <<<"$promotions")
		promotion=${promotion:-missing}
		case "$promotion" in
		success) green=$((green + 1)) ;;
		failure) failing+=("$flavor") ;;
		# skipped / missing / cancelled / null: nothing asserted this cell.
		*) unreached+=("$flavor") ;;
		esac
	done
	total_green=$((total_green + green))
	total_unreached=$((total_unreached + ${#unreached[@]}))

	failing_text=$(join_or_dash "${failing[@]+"${failing[@]}"}")
	unreached_text=$(join_or_dash "${unreached[@]+"${unreached[@]}"}")

	# A cancelled run is reported as cancelled, not as a failure.
	case "$conclusion" in
	success) icon='✅' ;;
	failure) icon='❌' ;;
	cancelled) icon='🚫' ;;
	*) icon='⬜' ;;
	esac
	printf '| %s `%s` | **%d/%d** | [%s %s](%s) | %s | %s |\n' \
		"$emoji" "$variant" "$green" "$count" "$icon" "$run_date" "$run_url" "$failing_text" "$unreached_text" >>"$tmp_table"
done < <(yq -r '.variants[] | [.id, .emoji] | @tsv' "$config")

percent=$((100 * total_green / total_cells))
total_failing=$((total_cells - total_green - total_unreached))
{
	echo
	echo "**Current image coverage: ${total_green}/${total_cells} cells (${percent}%)** — of the remainder, **${total_failing} failing** and **${total_unreached} never reached** (no job asserted them). The two are reported separately on purpose: a never-reached cell is untested, not broken. This is a point-in-time CI snapshot, not a support-tier promise."
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
