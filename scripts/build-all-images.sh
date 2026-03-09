#!/usr/bin/env bash
set -euo pipefail

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Define available variants
STABLE_VARIANTS=("yellowfin" "albacore")
EXPERIMENTAL_VARIANTS=("skipjack" "bonito")

# Parse command line arguments
BASE_ONLY=false
INCLUDE_EXPERIMENTAL=false
USE_TMUX=false
INCLUDE_KDE=false

while [[ $# -gt 0 ]]; do
case $1 in
--base-only)
BASE_ONLY=true
shift
;;
--include-experimental)
INCLUDE_EXPERIMENTAL=true
shift
;;
--include-kde)
INCLUDE_KDE=true
shift
;;
--tmux)
USE_TMUX=true
shift
;;
--help | -h)
echo "Usage: $0 [OPTIONS]"
echo "Options:"
echo "  --base-only              Build only base flavors (skip hwe/gdx and kde chain)"
echo "  --include-experimental   Include experimental variants (skipjack, bonito)"
echo "  --include-kde            Include KDE flavor chain (kde, kde-hwe, kde-gdx)"
echo "  --tmux                   Launch a tmux session to monitor logs"
echo "  --help, -h               Show this help message"
exit 0
;;
*)
echo "Unknown option: $1"
echo "Use --help for usage information"
exit 1
;;
esac
done

# Determine which variants to build
if [[ "$INCLUDE_EXPERIMENTAL" == "true" ]]; then
VARIANTS=("${STABLE_VARIANTS[@]}" "${EXPERIMENTAL_VARIANTS[@]}")
else
VARIANTS=("${STABLE_VARIANTS[@]}")
fi

# Display build configuration
if [[ "$BASE_ONLY" == "true" ]]; then
echo -e "${CYAN}Starting concurrent builds for base variants only...${NC}"
echo -e "${WHITE}Building variants: ${VARIANTS[*]}${NC}"
else
echo -e "${CYAN}Starting concurrent builds for all flavors (base -> hwe -> gdx)...${NC}"
if [[ "$INCLUDE_KDE" == "true" ]]; then
echo -e "${WHITE}Including KDE chain: kde -> kde-hwe -> kde-gdx${NC}"
fi
echo -e "${WHITE}Building variants: ${VARIANTS[*]}${NC}"
fi

# Create log directory
LOG_DIR=".build-logs"
mkdir -p "$LOG_DIR"

# Create a timestamp for this build session
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

echo -e "${BLUE}Logs will be saved to: $LOG_DIR/${NC}"

# Function to setup tmux session for log monitoring
setup_tmux_monitoring() {
local session_name="tunaos-build-${TIMESTAMP}"
local variants=("$@")

echo -e "${CYAN}Setting up tmux session: $session_name${NC}"

if ! command -v tmux &>/dev/null; then
echo -e "${RED}tmux is not installed. Please install tmux or run without the --tmux flag.${NC}"
return 1
fi

tmux kill-session -t "$session_name" 2>/dev/null || true
tmux new-session -d -s "$session_name"
tmux split-window -h -t "$session_name"
tmux split-window -v -t "$session_name:0.0"
tmux split-window -v -t "$session_name:0.1"

local pane=0
for variant in "${variants[@]}"; do
if [[ $pane -lt 4 ]]; then
local log_file="$LOG_DIR/${variant}_${TIMESTAMP}.log"
local cmd="echo 'Waiting for $variant log...' && while [[ ! -f '$log_file' ]]; do sleep 1; done && tail -n +1 -f '$log_file'"
tmux send-keys -t "$session_name:0.$pane" "$cmd" Enter
((pane++))
fi
done

while [[ $pane -lt 4 ]]; do
tmux send-keys -t "$session_name:0.$pane" "echo 'TunaOS Build Monitor - Pane $((pane + 1))'; watch -n 5 'ls -lha $LOG_DIR/'" Enter
((pane++))
done

echo -e "${GREEN}Tmux session created. Monitor logs with:${NC}"
echo -e "${WHITE}  tmux attach-session -t $session_name${NC}"
}

build_variant_pipeline() {
local variant=$1
local base_only=${2:-false}
local log_file="$LOG_DIR/${variant}_${TIMESTAMP}.log"

exec >"$log_file" 2>&1

echo "=== Started $variant pipeline at $(date) ==="
echo "Logging to: $log_file"

echo "Building $variant base..."
if just build "$variant" base; then
echo "$variant base completed at $(date)"
else
echo "$variant base failed at $(date)"
exit 1
fi

if [[ "$base_only" == "true" ]]; then
echo "$variant base-only build finished successfully at $(date)"
echo "=== Completed $variant base-only pipeline at $(date) ==="
return
fi

echo "Building $variant hwe..."
if just build "$variant" hwe; then
echo "$variant hwe completed at $(date)"
else
echo "$variant hwe failed at $(date)"
exit 1
fi

echo "Building $variant gdx..."
if just build "$variant" gdx; then
echo "$variant gdx completed at $(date)"
else
echo "$variant gdx failed at $(date)"
exit 1
fi

if [[ "$INCLUDE_KDE" == "true" ]]; then
echo "Building $variant kde..."
if just build "$variant" kde; then
echo "$variant kde completed at $(date)"
else
echo "$variant kde failed at $(date)"
exit 1
fi

echo "Building $variant kde-hwe..."
if just build "$variant" kde-hwe; then
echo "$variant kde-hwe completed at $(date)"
else
echo "$variant kde-hwe failed at $(date)"
exit 1
fi

echo "Building $variant kde-gdx..."
if just build "$variant" kde-gdx; then
echo "$variant kde-gdx completed at $(date)"
else
echo "$variant kde-gdx failed at $(date)"
exit 1
fi
fi

echo "$variant complete pipeline finished successfully at $(date)"
echo "=== Completed $variant pipeline at $(date) ==="
}

export -f build_variant_pipeline
export LOG_DIR
export TIMESTAMP
export BASE_ONLY
export INCLUDE_KDE

declare -a PIDS
declare -a VARIANT_NAMES

for variant in "${VARIANTS[@]}"; do
build_variant_pipeline "$variant" "$BASE_ONLY" &
PIDS+=($!)
VARIANT_NAMES+=("$variant")
echo -e "${CYAN}Started $variant pipeline (PID: ${PIDS[-1]})${NC} - Log: ${BLUE}$LOG_DIR/${variant}_${TIMESTAMP}.log${NC}"
done

if [[ "$USE_TMUX" == "true" ]]; then
setup_tmux_monitoring "${VARIANTS[@]}"
fi

echo ""
echo -e "${YELLOW}Waiting for all background builds to complete...${NC}"

if [[ "$USE_TMUX" != "true" ]]; then
echo -e "${WHITE}Tip: Use the --tmux flag to set up a monitoring session.${NC}"
fi
echo ""

SUCCESS=true
for i in "${!PIDS[@]}"; do
pid=${PIDS[$i]}
variant=${VARIANT_NAMES[$i]}

if wait "$pid"; then
echo -e "${GREEN}$variant pipeline completed successfully${NC}"
else
echo -e "${RED}$variant pipeline FAILED. Check log: $LOG_DIR/${variant}_${TIMESTAMP}.log${NC}"
SUCCESS=false
fi
done

echo ""
if [[ "$SUCCESS" == "true" ]]; then
echo -e "${GREEN}All variant pipelines completed successfully!${NC}"
echo -e "${BLUE}Build logs are saved in: $LOG_DIR/${NC}"
exit 0
else
echo -e "${RED}One or more builds failed. Please review the logs.${NC}"
exit 1
fi
