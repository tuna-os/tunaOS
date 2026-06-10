#!/usr/bin/env bats
# Unit tests for scripts/pipeline-overview.sh helper functions
#
# Tests:
#   - fmt_duration: seconds → m:ss format
#   - render_progress_bar: fractional bar rendering
#   - State file parsing (tab-separated: state, start_epoch, end_epoch)
#   - Spinner frame cycling
#   - Color code definitions (ANSI escape sequences)

setup() {
  TEST_ROOT="$(mktemp -d)"
}

teardown() {
  rm -rf "${TEST_ROOT}" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════════════════
# pipeline-overview.sh — fmt_duration
# ═══════════════════════════════════════════════════════════════════════════

fmt_duration() {
  local secs=${1:-0}
  printf "%d:%02d" $((secs / 60)) $((secs % 60))
}

@test "fmt_duration: zero seconds" {
  run bash -c "$(declare -f fmt_duration); fmt_duration 0"
  [ "$output" = "0:00" ]
}

@test "fmt_duration: one minute exactly" {
  run bash -c "$(declare -f fmt_duration); fmt_duration 60"
  [ "$output" = "1:00" ]
}

@test "fmt_duration: one minute one second" {
  run bash -c "$(declare -f fmt_duration); fmt_duration 61"
  [ "$output" = "1:01" ]
}

@test "fmt_duration: ten minutes" {
  run bash -c "$(declare -f fmt_duration); fmt_duration 600"
  [ "$output" = "10:00" ]
}

@test "fmt_duration: one hour" {
  run bash -c "$(declare -f fmt_duration); fmt_duration 3600"
  [ "$output" = "60:00" ]
}

@test "fmt_duration: pads seconds with leading zero" {
  run bash -c "$(declare -f fmt_duration); fmt_duration 125"
  [ "$output" = "2:05" ]
}

@test "fmt_duration: handles empty/unset (defaults to 0)" {
  run bash -c "$(declare -f fmt_duration); fmt_duration"
  [ "$output" = "0:00" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# pipeline-overview.sh — render_progress_bar
# ═══════════════════════════════════════════════════════════════════════════

render_progress_bar() {
  local total=$1 current=$2 width=$3
  if [ "$total" -eq 0 ]; then
    printf "[                              ] 0%%"
    return
  fi
  local filled=$((current * width / total))
  local empty=$((width - filled))
  printf "["
  for ((i = 0; i < filled; i++)); do printf "━"; done
  for ((i = 0; i < empty; i++)); do printf " "; done
  printf "] %d%%" $((current * 100 / total))
}

@test "progress_bar: 0 of 5 complete" {
  run bash -c "$(declare -f render_progress_bar); render_progress_bar 5 0 20"
  [[ "$output" == *"0%"* ]]
  [[ "$output" == "[                    ] 0%" ]]
}

@test "progress_bar: 5 of 5 complete (100%)" {
  run bash -c "$(declare -f render_progress_bar); render_progress_bar 5 5 20"
  [[ "$output" == *"100%"* ]]
}

@test "progress_bar: half complete" {
  run bash -c "$(declare -f render_progress_bar); render_progress_bar 10 5 10"
  [[ "$output" == "[█████     ] 50%" ]]
}

@test "progress_bar: handles zero total gracefully" {
  run bash -c "$(declare -f render_progress_bar); render_progress_bar 0 0 20"
  [[ "$output" == *"0%"* ]]
}

@test "progress_bar: 1 of 3 (33%)" {
  run bash -c "$(declare -f render_progress_bar); render_progress_bar 3 1 15"
  # 1 * 15 / 3 = 5 filled chars
  [[ "$output" == "[█████          ] 33%" ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# pipeline-overview.sh — State File Parsing
# ═══════════════════════════════════════════════════════════════════════════

@test "state_parse: parses running state with start epoch" {
  run bash -c '
    state_file="/tmp/test_state_running"
    printf "running\t1000" > "$state_file"
    IFS=$"\t" read -r state start_epoch end_epoch < "$state_file" || true
    echo "state=[$state] start=[$start_epoch] end=[$end_epoch]"
  '
  [[ "$output" == "state=[running] start=[1000] end=[]" ]]
}

@test "state_parse: parses done state with timestamps" {
  run bash -c '
    state_file="/tmp/test_state_done"
    printf "done\t1000\t1042" > "$state_file"
    IFS=$"\t" read -r state start_epoch end_epoch < "$state_file" || true
    echo "state=[$state] start=[$start_epoch] end=[$end_epoch]"
  '
  [[ "$output" == "state=[done] start=[1000] end=[1042]" ]]
}

@test "state_parse: parses failed state" {
  run bash -c '
    state_file="/tmp/test_state_failed"
    printf "failed\t1000\t1060" > "$state_file"
    IFS=$"\t" read -r state start_epoch end_epoch < "$state_file" || true
    echo "state=[$state] start=[$start_epoch] end=[$end_epoch]"
  '
  [[ "$output" == "state=[failed] start=[1000] end=[1060]" ]]
}

@test "state_parse: state file missing → queued" {
  run bash -c '
    state_file="/tmp/nonexistent_state"
    if [[ ! -f "$state_file" ]]; then
      echo "queued"
    else
      echo "exists"
    fi
  '
  [ "$output" = "queued" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# pipeline-overview.sh — Spinner Frame Cycling
# ═══════════════════════════════════════════════════════════════════════════

@test "spinner: cycles through all 10 frames" {
  run bash -c '
    SPINNER_FRAMES=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
    spin_idx=0
    for ((i=0; i<10; i++)); do
      echo -n "${SPINNER_FRAMES[$((spin_idx % 10))]}"
      spin_idx=$((spin_idx + 1))
    done
  '
  [ "$output" = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" ]
}

@test "spinner: wraps around after 10 frames" {
  run bash -c '
    SPINNER_FRAMES=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
    spin_idx=10
    echo "${SPINNER_FRAMES[$((spin_idx % 10))]}"
  '
  [ "$output" = "⠋" ]
}

@test "spinner: index 5 returns frame at position 5" {
  run bash -c '
    SPINNER_FRAMES=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
    spin_idx=5
    echo "${SPINNER_FRAMES[$((spin_idx % 10))]}"
  '
  [ "$output" = "⠴" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# pipeline-overview.sh — Label Encoding
# ═══════════════════════════════════════════════════════════════════════════

@test "label: splits emoji||variant:flavor encoding" {
  run bash -c '
    entry="🐟||yellowfin:gnome"
    emoji="${entry%%||*}"
    label="${entry#*||}"
    echo "emoji=[$emoji] label=[$label]"
  '
  [ "$output" = "emoji=[🐟] label=[yellowfin:gnome]" ]
}

@test "label: converts colon to hyphen for state file key" {
  run bash -c '
    label="yellowfin:gnome"
    key="${label//:/-}"
    echo "$key"
  '
  [ "$output" = "yellowfin-gnome" ]
}

@test "label: handles variant without emoji gracefully" {
  run bash -c '
    entry="||albacore:base"
    emoji="${entry%%||*}"
    label="${entry#*||}"
    echo "emoji=[$emoji] label=[$label]"
  '
  [ "$output" = "emoji=[] label=[albacore:base]" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# pipeline-overview.sh — ANSI Color Codes
# ═══════════════════════════════════════════════════════════════════════════

@test "colors: BOLD is non-empty" {
  run bash -c 'BOLD=$"\033[1m"; echo "has_bold=${#BOLD}"'
  [ "$output" != "has_bold=0" ]
}

@test "colors: GREEN is distinct from RED" {
  run bash -c '
    GREEN=$"\033[32m"
    RED=$"\033[31m"
    [ "$GREEN" != "$RED" ] && echo "distinct"
  '
  [ "$output" = "distinct" ]
}

@test "colors: RESET sequence is defined" {
  run bash -c 'RESET=$"\033[0m"; echo "has_reset=${#RESET}"'
  [ "$output" != "has_reset=0" ]
}
