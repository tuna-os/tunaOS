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
	--tmux)
		USE_TMUX=true
		shift
		;;
	--help | -h)
		echo "Usage: $0 [OPTIONS]"
		echo "Options:"
		echo "  --base-only              Build only base flavors (skip dx/gdx)"
		echo "  --include-experimental   Include experimental variants (skipjack, bonito)"
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
	echo -e "${CYAN}🚀 Starting concurrent builds for base variants only...${NC}"
	echo -e "${WHITE}Building variants: ${VARIANTS[*]}${NC}"
else
	echo -e "${CYAN}🚀 Starting concurrent builds for all flavors (base → dx → gdx)...${NC}"
	echo -e "${WHITE}Building variants: ${VARIANTS[*]}${NC}"
fi

# Create log directory
LOG_DIR=".build-logs"
mkdir -p "$LOG_DIR"

# Create a timestamp for this build session
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

echo -e "${BLUE}📁 Logs will be saved to: $LOG_DIR/${NC}"

# Function to setup tmux session for log monitoring
setup_tmux_monitoring() {
	local session_name="tunaos-build-${TIMESTAMP}"
	local variants=("$@")

	echo -e "${CYAN}🖥️  Setting up tmux session: $session_name${NC}"

	# Check if tmux is available
	if ! command -v tmux &>/dev/null; then
		echo -e "${RED}❌ tmux is not installed. Please install tmux or run without the --tmux flag.${NC}"
		return 1
	fi

	# Kill any old session with the same name to avoid conflicts
	tmux kill-session -t "$session_name" 2>/dev/null || true

	# Create new tmux session
	tmux new-session -d -s "$session_name"

	# Split into a 2x2 grid
	tmux split-window -h -t "$session_name"
	tmux split-window -v -t "$session_name:0.0"
	tmux split-window -v -t "$session_name:0.1"

	# Setup each pane to tail a log file
	local pane=0
	for variant in "${variants[@]}"; do
		if [[ $pane -lt 4 ]]; then
			local log_file="$LOG_DIR/${variant}_${TIMESTAMP}.log"
			# Wait for log file, then tail from the beginning (-n +1) and follow (-f)
			local cmd="echo '📺 Waiting for $variant log...' && while [[ ! -f '$log_file' ]]; do sleep 1; done && tail -n +1 -f '$log_file'"
			tmux send-keys -t "$session_name:0.$pane" "$cmd" Enter
			((pane++))
		fi
	done

	# If we have fewer than 4 variants, show a summary in remaining panes
	while [[ $pane -lt 4 ]]; do
		tmux send-keys -t "$session_name:0.$pane" "echo 'TunaOS Build Monitor - Pane $((pane + 1))'; watch -n 5 'ls -lha $LOG_DIR/'" Enter
		((pane++))
	done

	# Instruct the user how to attach instead of blocking the script
	echo -e "${GREEN}🚀 Tmux session created. Monitor the build logs by running:${NC}"
	echo -e "${WHITE}   tmux attach-session -t $session_name${NC}"
}

# Define a function to build a complete variant pipeline with logging
build_variant_pipeline() {
	local emoji=$1
	local variant=$2
	local base_only=${3:-false}
	local log_file="$LOG_DIR/${variant}_${TIMESTAMP}.log"

	# Redirect all output of this function to the log file.
	# The exec command replaces the shell process with one that has its
	# stdout/stderr redirected, which is very efficient for logging.
	exec >"$log_file" 2>&1

	echo "🏗️  === Started $variant pipeline at $(date) ==="
	echo "📝 Logging to: $log_file"

	# Base build
	echo "🔨 Building $variant base..."
	if just build "$variant" base; then
		echo "✅ $variant base completed at $(date)"
	else
		echo "❌ $variant base failed at $(date)"
		exit 1
	fi

	# Skip DX and GDX if base_only is true
	if [[ "$base_only" == "true" ]]; then
		echo "🎉 $variant base-only build finished successfully at $(date)"
		echo "🏁 === Completed $variant base-only pipeline at $(date) ==="
		return
	fi

	# DX build (depends on base)
	echo "🛠️  Building $variant dx..."
	if just build "$variant" dx; then
		echo "✅ $variant dx completed at $(date)"
	else
		echo "❌ $variant dx failed at $(date)"
		exit 1
	fi

	# GDX build (depends on dx)
	echo "🎮 Building $variant gdx..."
	if just build "$variant" gdx; then
		echo "✅ $variant gdx completed at $(date)"
	else
		echo "❌ $variant gdx failed at $(date)"
		exit 1
	fi

	echo "🎉 $variant complete pipeline finished successfully at $(date)"
	echo "🏁 === Completed $variant pipeline at $(date) ==="
}

# Export the function and variables so background processes (subshells) can access them
export -f build_variant_pipeline
export LOG_DIR
export TIMESTAMP
export BASE_ONLY

# Declare arrays to hold process IDs and variant names
declare -a PIDS
declare -a VARIANT_NAMES

# Start variant pipelines in the background
for variant in "${VARIANTS[@]}"; do
	# Get emoji for variant
	case $variant in
	yellowfin) emoji="🐠" ;;
	albacore) emoji="🐟" ;;
	skipjack) emoji="🏛️ " ;;
	bonito) emoji="🎩" ;;
	*) emoji="⚙️" ;;
	esac

	# Run the build function in a background subshell
	build_variant_pipeline "$emoji" "$variant" "$BASE_ONLY" &

	# Store the PID and name for later
	PIDS+=($!)
	VARIANT_NAMES+=("$variant")

	echo -e "${CYAN}${emoji} Started $variant pipeline (PID: ${PIDS[-1]})${NC} - Log: ${BLUE}$LOG_DIR/${variant}_${TIMESTAMP}.log${NC}"
done

# Launch tmux session if requested. This function no longer blocks.
if [[ "$USE_TMUX" == "true" ]]; then
	setup_tmux_monitoring "${VARIANTS[@]}"
fi

# Wait for all pipelines to complete and check their exit codes
echo ""
echo -e "${YELLOW}⏳ Waiting for all background builds to complete...${NC}"

if [[ "$USE_TMUX" != "true" ]]; then
	echo -e "${WHITE}💡 Tip: Use the --tmux flag to automatically set up a monitoring session.${NC}"
fi
echo ""

# Wait for all processes and check their exit codes
SUCCESS=true
for i in "${!PIDS[@]}"; do
	pid=${PIDS[$i]}
	variant=${VARIANT_NAMES[$i]}

	# Get emoji for variant
	case $variant in
	yellowfin) emoji="🐠" ;;
	albacore) emoji="🐟" ;;
	skipjack) emoji="🏛️ " ;;
	bonito) emoji="🎩" ;;
	*) emoji="⚙️" ;;
	esac

	if wait "$pid"; then
		echo -e "${GREEN} ${emoji} ✅ $variant pipeline completed successfully${NC}"
	else
		echo -e "${RED} ${emoji} ❌ $variant pipeline FAILED. Check log: $LOG_DIR/${variant}_${TIMESTAMP}.log${NC}"
		SUCCESS=false
	fi
done

echo ""
if [[ "$SUCCESS" == "true" ]]; then
	echo -e "${GREEN}🎉 All variant pipelines completed successfully!${NC}"
	echo -e "${BLUE}📁 Build logs are saved in: $LOG_DIR/${NC}"
	exit 0
else
	echo -e "${RED}🔥 One or more builds failed. Please review the logs.${NC}"
	exit 1
fi
