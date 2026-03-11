#!/usr/bin/env bash
# Pipeline overview pane — run by zellij, patched at runtime by `just pipeline`.
# Placeholders (__STATUS_DIR__ etc.) are replaced by sed before this runs.
# Do not invoke directly.

STATUS_DIR="__STATUS_DIR__"
STAGE_NAME="__STAGE_NAME__"
CURRENT_STAGE=__CURRENT_STAGE__
TOTAL_STAGES=__TOTAL_STAGES__
LABELS=(__LABELS__)

SPINNER_FRAMES=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
spin_idx=0

BOLD=$'\033[1m'
DIM=$'\033[2m'
GREEN=$'\033[32m'
RED=$'\033[31m'
YELLOW=$'\033[33m'
CYAN=$'\033[36m'
RESET=$'\033[0m'
CLEAR=$'\033[2J\033[H'

fmt_duration() {
	local secs=${1:-0}
	printf "%d:%02d" $((secs / 60)) $((secs % 60))
}

render_progress_bar() {
	local total=$1 current=$2 width=$3
	local filled=$((current * width / total))
	local empty=$((width - filled))
	printf "["
	for ((i = 0; i < filled; i++)); do printf "━"; done
	for ((i = 0; i < empty; i++)); do printf " "; done
	printf "] %d%%" $((current * 100 / total))
}

render() {
	local now spin all_done=1
	now=$(date +%s)
	spin="${SPINNER_FRAMES[$((spin_idx % ${#SPINNER_FRAMES[@]}))]}"

	local done_count=0 failed_count=0 running_count=0 queued_count=0
	local total_count=${#LABELS[@]}

	printf "%s" "$CLEAR"
	printf "%s\n" "${BOLD}${CYAN}  TunaOS Build Pipeline${RESET}"
	printf "  Stage %d / %d  —  %s\n\n" "$CURRENT_STAGE" "$TOTAL_STAGES" "$STAGE_NAME"
	printf "  %s%-30s  %-10s  %-7s%s\n" "$BOLD" "IMAGE" "STATUS" "TIME" "$RESET"
	printf "  %s\n" "──────────────────────────────────────────────────"

	for entry in "${LABELS[@]}"; do
		local emoji label key state state_file start_epoch end_epoch elapsed took
		# Labels are encoded as "emoji||variant:flavor" by pipeline.sh
		emoji="${entry%%||*}"
		label="${entry#*||}"
		local display_label="${emoji} ${label}"
		key="${label//:/-}"
		state_file="$STATUS_DIR/$key"

		if [[ ! -f "$state_file" ]]; then
			printf "  %-32s  %s%-10s%s  %s\n" "$display_label" "$DIM" "queued" "$RESET" "--:--"
			queued_count=$((queued_count + 1))
			all_done=0
			continue
		fi

		# Read tab-separated: state<TAB>start[<TAB>end]
		# Use || true to handle files without newlines
		IFS=$'\t' read -r state start_epoch end_epoch <"$state_file" || true

		# Ensure start_epoch and end_epoch are numbers
		if [[ ! "$start_epoch" =~ ^[0-9]+$ ]]; then start_epoch=$now; fi
		if [[ ! "$end_epoch" =~ ^[0-9]+$ ]]; then end_epoch=$now; fi

		elapsed=$((now - start_epoch))

		case "$state" in
		running)
			printf "  %-32s  %s%s %-8s%s  %s\n" \
				"$display_label" "$YELLOW" "$spin" "building" "$RESET" \
				"$(fmt_duration $elapsed)"
			running_count=$((running_count + 1))
			all_done=0
			;;
		done)
			took=$((end_epoch - start_epoch))
			printf "  %-32s  %s✓ %-8s%s  %s\n" \
				"$display_label" "$GREEN" "done" "$RESET" \
				"$(fmt_duration $took)"
			done_count=$((done_count + 1))
			;;
		failed)
			took=$((end_epoch - start_epoch))
			printf "  %-32s  %s✗ %-8s%s  %s\n" \
				"$display_label" "$RED" "FAILED" "$RESET" \
				"$(fmt_duration $took)"
			failed_count=$((failed_count + 1))
			;;
		*)
			printf "  %-32s  %s%-10s%s  %s\n" "$display_label" "$DIM" "unknown" "$RESET" "--:--"
			queued_count=$((queued_count + 1))
			all_done=0
			;;
		esac
	done

	local finished_count=$((done_count + failed_count))
	printf "\n  "
	render_progress_bar "$total_count" "$finished_count" 30
	printf "\n"

	printf "\n  %sDone: %d  %sFailed: %d  %sRunning: %d  %sQueued: %d%s\n" \
		"$GREEN" "$done_count" "$RED" "$failed_count" "$YELLOW" "$running_count" "$DIM" "$queued_count" "$RESET"

	printf "\n  %s.build-logs/   │   %s%s\n" "$DIM" "$(date '+%H:%M:%S')" "$RESET"

	if [[ "$all_done" == "1" ]]; then
		if [[ $failed_count -eq 0 ]]; then
			printf "\n  %sAll jobs complete successfully.%s\n" "${BOLD}${GREEN}" "$RESET"
		else
			printf "\n  %sStage finished with %d failures.%s\n" "${BOLD}${RED}" "$failed_count" "$RESET"
		fi
		exit 0
	fi
}

while true; do
	render
	spin_idx=$((spin_idx + 1))
	sleep 0.8
done
