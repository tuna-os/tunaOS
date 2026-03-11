#!/usr/bin/env bash
# Run the full staged build pipeline locally, mirroring the CI job graph.
# Reads .github/build-config.yml for the variant/flavor/stage structure.
# Builds within each stage run in parallel; stages are sequential.
#
# Requires zellij for the live UI (overview status board + one log pane per build).
# Falls back to prefixed stdout if zellij is not available.
# Logs always written to .build-logs/{variant}-{flavor}.log.
#
# Usage:
#   ./scripts/pipeline.sh [variant] [flavor] [tag] [dry_run]
#
# Example:
#   ./scripts/pipeline.sh yellowfin kde

set -euo pipefail

FILTER_VARIANT="${1:-all}"
FILTER_FLAVOR="${2:-all}"
TAG="${3:-latest}"
DRY_RUN="${4:-0}"
JUST="${JUST:-just}"
LOG_DIR=".build-logs"
mkdir -p "$LOG_DIR"

# ── Initialize submodules ────────────────────────────────────────────────
# Do this once before launching parallel builds to avoid .git lock contention.
STATUS_DIRS_TO_CLEAN=()

cleanup() {
	local exit_code=$?
	echo ""
	echo "Cleaning up..."
	# De-init submodules
	if [[ "${DRY_RUN:-0}" != "1" ]]; then
		echo "  ↳ De-initializing submodules..."
		git submodule deinit -f --all &>/dev/null || true
	fi
	# Clean status dirs
	for dir in "${STATUS_DIRS_TO_CLEAN[@]}"; do
		if [[ -d "$dir" ]]; then
			echo "  ↳ Removing status directory $dir"
			rm -rf "$dir"
		fi
	done
	exit $exit_code
}

trap cleanup EXIT INT TERM

if [[ "$DRY_RUN" != "1" ]]; then
	echo "Updating submodules..."
	git submodule update --init --recursive
	export SKIP_SUBMODULES=1
fi

# ── Helpers ──────────────────────────────────────────────────────────────

local_ref() { echo "localhost/${1}:${2}"; }

parent_for() {
	case "$1" in
	*-gdx-hwe) echo "base-hwe" ;;
	*-gdx) echo "base-gdx" ;;
	*-hwe) echo "base-hwe" ;;
	*) echo "" ;;
	esac
}

stage1_base_ref() { echo ""; }
stage2_base_ref() { local_ref "$1" "base"; }
stage3_base_ref() {
	local parent
	parent=$(parent_for "$2")
	if [[ -n "$parent" ]]; then
		local_ref "$1" "$parent"
	else
		echo "WARNING: no parent for stage-3 flavor '$2'" >&2
		echo ""
	fi
}

# ── Zellij detection ─────────────────────────────────────────────────────

USE_ZELLIJ=0
ZELLIJ_SOCKET_PATH=""
if command -v zellij &>/dev/null && [[ "$DRY_RUN" != "1" ]]; then
	if [[ -n "${ZELLIJ:-}" ]]; then
		USE_ZELLIJ=2
		ZELLIJ_SOCKET_PATH="${ZELLIJ_SOCKET:-}"
	elif [[ -n "${ZELLIJ_SOCKET:-}" ]]; then
		USE_ZELLIJ=2
		ZELLIJ_SOCKET_PATH="$ZELLIJ_SOCKET"
	else
		USE_ZELLIJ=1
	fi
fi

# ── Overview script builder ───────────────────────────────────────────────
# Copies scripts/pipeline-overview.sh to a temp file and substitutes the
# __PLACEHOLDER__ tokens so the script knows which stage and jobs to watch.
# Status files live in a per-stage temp dir as tab-separated state records:
#   running  -> "running\t<start_epoch>"
#   done     -> "done\t<start_epoch>\t<end_epoch>"
#   failed   -> "failed\t<start_epoch>\t<end_epoch>"

write_overview_script() {
	local out=$1 status_dir=$2 stage_name=$3 total=$4 current=$5
	shift 5
	local labels=("$@")
	local labels_str=""
	for l in "${labels[@]}"; do labels_str+="\"$l\" "; done

	cp "scripts/pipeline-overview.sh" "$out"
	sed -i \
		-e "s|__STATUS_DIR__|${status_dir}|g" \
		-e "s|__STAGE_NAME__|${stage_name}|g" \
		-e "s|__CURRENT_STAGE__|${current}|g" \
		-e "s|__TOTAL_STAGES__|${total}|g" \
		-e "s@__LABELS__@${labels_str}@g" \
		"$out"
	chmod +x "$out"
}

# ── KDL layout builder ────────────────────────────────────────────────────
# Overview pane pinned to 40 columns on the left.
# Log panes stacked vertically on the right.

write_zellij_layout() {
	local layout_file=$1 overview_script=$2
	shift 2
	local panes=("$@") # alternating: logfile label ...
	{
		echo 'layout {'
		echo '  pane split_direction="horizontal" {'
		printf '    pane size=20 name="Overview" {\n'
		printf '      command "%s"\n' "$overview_script"
		printf '    }\n'
		echo '    pane split_direction="vertical" {'
		local i=0
		while [[ $i -lt ${#panes[@]} ]]; do
			local logfile="${panes[$i]}" label="${panes[$((i + 1))]}"
			printf '      pane name="%s" {\n' "$label"
			printf '        command "tail"\n'
			printf '        args "-n" "50" "-f" "%s"\n' "$logfile"
			printf '      }\n'
			i=$((i + 2))
		done
		echo '    }'
		echo '  }'
		echo '}'
	} >"$layout_file"
}

# ── Parallel stage runner ─────────────────────────────────────────────────

TOTAL_STAGES=3
CURRENT_STAGE=0

run_stage() {
	local stage_name=$1 entries=$2 base_ref_fn=$3
	CURRENT_STAGE=$((CURRENT_STAGE + 1))
	[[ -z "$entries" ]] && return 0

	# Collect job metadata
	local -a vs=() fs=() logfiles=() base_refs=() labels=() pane_args=()
	local status_dir
	status_dir=$(mktemp -d /tmp/pipeline-status-XXXXXX)
	STATUS_DIRS_TO_CLEAN+=("$status_dir")

	while IFS=$'\t' read -r v f _s _emoji; do
		local base_ref
		base_ref=$("$base_ref_fn" "$v" "$f")
		local logfile="${LOG_DIR}/${v}-${f}.log"
		: >"$logfile"
		vs+=("$v")
		fs+=("$f")
		logfiles+=("$logfile")
		base_refs+=("$base_ref")
		labels+=("${_emoji}||${v}:${f}")
		pane_args+=("$logfile" "${v}:${f}")
	done <<<"$entries"

	local count=${#vs[@]}

	echo ""
	echo "╔══════════════════════════════════════════════════════════════╗"
	printf "║  Stage %d/%d — %-51s║\n" "$CURRENT_STAGE" "$TOTAL_STAGES" "$stage_name"
	echo "╚══════════════════════════════════════════════════════════════╝"
	echo "  Launching $count build(s) in parallel..."

	# Build zellij layout and overview script
	local layout_file overview_script zellij_session=""
	layout_file=$(mktemp /tmp/zellij-layout-XXXXXX.kdl)
	overview_script=$(mktemp /tmp/pipeline-overview-XXXXXX.sh)

	if [[ "$USE_ZELLIJ" == "1" ]] || [[ "$USE_ZELLIJ" == "2" ]]; then
		write_overview_script \
			"$overview_script" "$status_dir" \
			"$stage_name" "$TOTAL_STAGES" "$CURRENT_STAGE" \
			"${labels[@]}"
		write_zellij_layout "$layout_file" "$overview_script" "${pane_args[@]}"

		if [[ "$USE_ZELLIJ" == "1" ]]; then
			zellij_session="pipeline-$$-${CURRENT_STAGE}"
			# Launch zellij and wait until the session is actually reachable
			# before starting builds, so panes are ready to show output.
			# Use nohup and disown to keep zellij running after script exits.
			nohup zellij --session "$zellij_session" --layout "$layout_file" </dev/null &>/dev/null &
			disown $!
			local waited=0
			while ! zellij list-sessions 2>/dev/null | grep -q "$zellij_session"; do
				sleep 0.2
				waited=$((waited + 1))
				if [[ $waited -ge 25 ]]; then
					echo "  WARNING: zellij session did not start in 5s, continuing without UI"
					USE_ZELLIJ=0
					break
				fi
			done
			if [[ "$USE_ZELLIJ" == "1" ]]; then
				echo "  zellij session '$zellij_session' is live"
				echo "  attach in another terminal: zellij attach $zellij_session"
			fi
		elif [[ "$USE_ZELLIJ" == "2" ]]; then
			if [[ -n "$ZELLIJ_SOCKET_PATH" ]]; then
				ZELLIJ_SOCKET="$ZELLIJ_SOCKET_PATH" zellij action new-tab --layout "$layout_file" --name "Stage $CURRENT_STAGE"
			else
				zellij action new-tab --layout "$layout_file" --name "Stage $CURRENT_STAGE"
			fi
			echo "  zellij tab opened in current session."
		fi
	fi

	# Launch all builds in parallel.
	local -a pids=()
	for ((i = 0; i < count; i++)); do
		local v="${vs[$i]}" f="${fs[$i]}"
		local logfile="${logfiles[$i]}" base_ref="${base_refs[$i]}"
		local key="${v}-${f}"

		if [[ "$DRY_RUN" == "1" ]]; then
			echo "[dry-run] build $v $f (base: ${base_ref:-none})"
			pids+=(-1)
			continue
		fi

		# Capture loop vars into named locals before the subshell
		local _v="$v" _f="$f" _logfile="$logfile" _base_ref="$base_ref"
		local _key="$key" _status_dir="$status_dir"
		local _just="$JUST" _tag="$TAG" _use_zellij="$USE_ZELLIJ"

		(
			set +e
			start=$(date +%s)
			printf "%s\t%s" "running" "$start" >"$_status_dir/$_key"

			rc=0
			if [[ "$_use_zellij" == "1" ]] || [[ "$_use_zellij" == "2" ]]; then
				"$_just" build "$_v" "$_f" "" "0" "$_tag" "$_base_ref" \
					>"$_logfile" 2>&1 || rc=$?
			else
				"$_just" build "$_v" "$_f" "" "0" "$_tag" "$_base_ref" \
					2>&1 | while IFS= read -r line; do
					printf "[%s:%s] %s\n" "$_v" "$_f" "$line"
					printf "[%s:%s] %s\n" "$_v" "$_f" "$line" >>"$_logfile"
				done || rc=$?
			fi

			end=$(date +%s)
			if [[ $rc -eq 0 ]]; then
				printf "%s\t%s\t%s" "done" "$start" "$end" >"$_status_dir/$_key"
			else
				printf "%s\t%s\t%s" "failed" "$start" "$end" >"$_status_dir/$_key"
				exit $rc
			fi
		) &
		pids+=($!)
		echo "  ↳ ${v}:${f}  pid=$!  log=${logfile}"
	done

	echo ""

	# Wait for all builds and collect results
	local any_failed=0
	for ((i = 0; i < count; i++)); do
		local pid="${pids[$i]}"
		[[ "$pid" == "-1" ]] && continue
		local code=0
		wait "$pid" || code=$?
		local v="${vs[$i]}" f="${fs[$i]}"
		if [[ $code -ne 0 ]]; then
			echo "  ✗  ${v}:${f}  (exit $code — see ${logfiles[$i]})"
			any_failed=1
		else
			echo "  ✓  ${v}:${f}"
		fi
	done

	# Tear down zellij session
	if [[ "$USE_ZELLIJ" == "1" ]] && [[ -n "$zellij_session" ]]; then
		sleep 2
		zellij delete-session "$zellij_session" --force 2>/dev/null || true
	fi
	rm -f "$layout_file" "$overview_script"

	if [[ $any_failed -ne 0 ]]; then
		echo ""
		echo "✗  Stage '$stage_name' failed — aborting pipeline."
		echo "   Logs: $LOG_DIR/"
		return 1
	fi
	echo "  ✓  Stage complete."
}

# ── Load config & filter ─────────────────────────────────────────────────

ENTRIES=$(yq -o=json '.' .github/build-config.yml | jq -r '
    .variants[]
    | . as $v
    | .flavors[]
    | select(
        ("'"$FILTER_VARIANT"'" == "all" or $v.id == "'"$FILTER_VARIANT"'") and
        ("'"$FILTER_FLAVOR"'" == "all" or .id == "'"$FILTER_FLAVOR"'")
      )
    | [$v.id, .id, (.stage | tostring), ($v.emoji // "🐡")] | join("\t")
')

if [[ -z "$ENTRIES" ]]; then
	echo "No entries for variant='$FILTER_VARIANT' flavor='$FILTER_FLAVOR'."
	exit 1
fi

STAGE1=$(echo "$ENTRIES" | awk -F'\t' '$3 == "1"' || true)
STAGE2=$(echo "$ENTRIES" | awk -F'\t' '$3 == "2"' || true)
STAGE3=$(echo "$ENTRIES" | awk -F'\t' '$3 == "3"' || true)

count_lines() {
	if [[ -z "${1:-}" ]]; then
		echo 0
	else
		echo "$1" | wc -l | tr -d ' '
	fi
}
total=$(echo "$ENTRIES" | wc -l | tr -d ' ')

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  TunaOS Pipeline                                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo "  Images : $total  ($(count_lines "$STAGE1") + $(count_lines "$STAGE2") + $(count_lines "$STAGE3") across 3 stages)"
echo "  Filter : variant=${FILTER_VARIANT}  flavor=${FILTER_FLAVOR}  tag=${TAG}"
if [[ "$USE_ZELLIJ" == "1" ]] || [[ "$USE_ZELLIJ" == "2" ]]; then
	echo "  UI     : zellij  (overview + per-build log panes)"
else
	echo "  UI     : inline  (install zellij for live panes)"
fi
[[ "$DRY_RUN" == "1" ]] && echo "  Mode   : DRY RUN"
echo ""

run_stage "base images" "$STAGE1" stage1_base_ref
run_stage "base-hwe / base-gdx / desktop" "$STAGE2" stage2_base_ref
run_stage "HWE / GDX desktop flavors" "$STAGE3" stage3_base_ref

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Pipeline complete ✓                                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
