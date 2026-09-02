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
composite_green=0

# The boots criterion's scope, read from the criteria file so this script and
# the composite scoreboard cannot disagree about which cells CI can boot.
mapfile -t boots_excl_flavors < <(yq -r '.criteria[] | select(.id == "boots") | .scope.excludes_flavors[]?' .github/green-criteria.yml)
mapfile -t boots_excl_suffixes < <(yq -r '.criteria[] | select(.id == "boots") | .scope.excludes_flavor_suffixes[]?' .github/green-criteria.yml)

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
	stage_jobs=$(gh api --paginate "repos/${repo}/actions/runs/${run_id}/jobs?per_page=100" \
		--jq '.jobs[] | select((.name | endswith(" / Promote")) or (.name | endswith(" / Gate"))) | [.name, .conclusion] | @tsv')

	# Three outcomes, not two. A cell only counts as FAILING when a job ran and
	# said so; "no Promote job existed" and "an upstream job stopped it" are
	# absence of evidence, and reporting them as failures is the conflation
	# docs/MATRIX-STATUS.md exists to prevent (tunaOS#1730). On 2026-08-14, 14
	# flavors across sailfin/marlin/flounder/gurnard produced no job at all --
	# their stage-2 group never ran because the base manifest failed first
	# (tunaOS#1729) -- and the table called every one of them blocked or
	# failing.
	green=0
	cgreen=0
	failing=()
	unreached=()
	for flavor in "${configured[@]}"; do
		promotion=$(awk -F '\t' -v suffix="/ ${flavor} / Promote" \
			'index($1, suffix) == length($1) - length(suffix) + 1 { result=$2 } END { print result }' <<<"$stage_jobs")
		promotion=${promotion:-missing}
		# Two jobs can render as "<flavor> / Gate" (the desktop Gate skipped
		# on base, the base Gate skipped on desktops) — prefer a real verdict
		# over its skipped twin, matching gen-matrix-status.py.
		gate=$(awk -F '\t' -v suffix="/ ${flavor} / Gate" \
			'index($1, suffix) == length($1) - length(suffix) + 1 {
				if ($2 == "success" || $2 == "failure") { result=$2 }
				else if (result == "") { result=$2 }
			} END { print result }' <<<"$stage_jobs")
		gate=${gate:-missing}
		case "$promotion" in
		success) green=$((green + 1)) ;;
		failure) failing+=("$flavor") ;;
		# skipped / missing / cancelled / null: nothing asserted this cell.
		*) unreached+=("$flavor") ;;
		esac
		# Composite: every blocking criterion, scoped. `builds` = promotion;
		# `boots` = the Gate, except where green-criteria.yml's scope says CI
		# cannot boot the cell (boots_excl_* below). A skipped or absent Gate
		# is NOT green (skipped_is_not_green).
		if [[ "$promotion" == "success" ]]; then
			gate_scoped=true
			for ex in "${boots_excl_flavors[@]}"; do
				[[ "$flavor" == "$ex" ]] && gate_scoped=false
			done
			for suf in "${boots_excl_suffixes[@]}"; do
				[[ "$flavor" == *"$suf" ]] && gate_scoped=false
			done
			if [[ "$gate_scoped" == false || "$gate" == "success" ]]; then
				cgreen=$((cgreen + 1))
			fi
		fi
	done
	total_green=$((total_green + green))
	composite_green=$((composite_green + cgreen))
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

# Family images built elsewhere (build-config `sibling_images:`). Rendered
# after the variant table and OUTSIDE its totals: they are not cells here.
"$(dirname "${BASH_SOURCE[0]}")/sibling-images-status.sh" "$config" >>"$tmp_table"

percent=$((100 * total_green / total_cells))
total_failing=$((total_cells - total_green - total_unreached))

# Composite green, scored against .github/green-criteria.yml.
#
# This script can only score two of the criteria itself: `builds` (promotion)
# and `boots` (the Gate), both readable from Actions job names. Every other
# criterion — desktop contract, silent omissions, ISO, install — is asserted
# by a workflow whose result lives elsewhere, and scripts/gen-matrix-status.py
# is what collates all of them into docs/MATRIX-STATUS.md.
#
# So: while the blocking set is a subset of what this script measures, it
# scores its own number. The moment anything else graduates to blocking, it
# stops guessing and takes gen-matrix-status.py's count verbatim, over that
# document's own denominator (which counts published cells, not build cells,
# and so can differ from the table above). Refusing to publish at all was the
# previous behaviour, and it froze the README block for two weeks after
# `desktop` and `no_silent_omissions` graduated on 2026-08-19.
mapfile -t blocking_ids < <(yq -r '.criteria[] | select(.enforcement == "blocking") | .id' .github/green-criteria.yml | sort)
blocking=$(IFS=,; echo "${blocking_ids[*]}")
composite_scope="this table"
composite_total=$total_cells
scorable=true
for id in "${blocking_ids[@]}"; do
	case "$id" in
	builds | boots) ;;
	*) scorable=false ;;
	esac
done
if [[ "$scorable" == false ]]; then
	# "**68 of 145** published cells are composite-green." — the sentence
	# gen-matrix-status.py writes. Anchored on the whole phrase so a
	# reworded document fails loudly here rather than silently matching
	# some other bolded pair of numbers.
	matrix_doc=${MATRIX_STATUS_DOC:-docs/MATRIX-STATUS.md}
	composite_line=$(grep -oE '\*\*[0-9]+ of [0-9]+\*\* published cells are composite-green' "$matrix_doc" || true)
	if [[ -z "$composite_line" ]]; then
		echo "::error::green-criteria.yml blocks on [${blocking}], which this script cannot score, and ${matrix_doc} carries no \"**N of M** published cells are composite-green\" line to source it from. Run scripts/gen-matrix-status.py first." >&2
		exit 1
	fi
	composite_green=$(sed -E 's/^\*\*([0-9]+) of .*/\1/' <<<"$composite_line")
	composite_total=$(sed -E 's/^\*\*[0-9]+ of ([0-9]+)\*\*.*/\1/' <<<"$composite_line")
	composite_scope="published cells, per [docs/MATRIX-STATUS.md](docs/MATRIX-STATUS.md)"
fi
blocking_text=$(sed -E 's/,/`, `/g' <<<"$blocking")

{
	echo
	echo "**Built ${total_green}/${total_cells} · composite green ${composite_green}/${composite_total} (${percent}% built)** — of the remainder, **${total_failing} failing** and **${total_unreached} never reached** (no job asserted them). The two are reported separately on purpose: a never-reached cell is untested, not broken. Composite green counts ${composite_scope} and is scored against [\`.github/green-criteria.yml\`](.github/green-criteria.yml), blocking today on \`${blocking_text}\` — every one of those a cell must satisfy, with skipped and never-tested counting as not green. The full per-axis board is [docs/MATRIX-STATUS.md](docs/MATRIX-STATUS.md). This is a point-in-time CI snapshot, not a support-tier promise."
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
