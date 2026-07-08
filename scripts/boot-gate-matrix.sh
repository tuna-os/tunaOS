#!/usr/bin/env bash
# scripts/boot-gate-matrix.sh — Boot-gate a matrix of images in parallel.
#
# Fans `scripts/boot-gate.sh` out across the KubeVirt cluster with bounded
# concurrency, round-robining VMs across nodes so neither node OOMs. Each gate
# builds a bootc disk, boots it, waits for SSH, and runs the tier-1 health
# checks; the matrix passes only if every gate passes.
#
# Usage:
#   scripts/boot-gate-matrix.sh <variant[:flavor]> [more...]
#   scripts/boot-gate-matrix.sh yellowfin:gnome yellowfin:kde albacore:gnome
#   scripts/boot-gate-matrix.sh yellowfin           # expands to the default set
#
# Environment:
#   GATE_CONCURRENCY   — max gates in flight (default: 3)
#   GATE_NODES         — space/comma list of nodes to round-robin (default: auto-detect)
#   GATE_FLAVORS       — default flavors when a bare variant is given
#                        (default: "gnome kde cosmic niri xfce")
#   REPO_ORGANIZATION  — GHCR org (default: tuna-os)
#   GATE_TIMEOUT       — per-gate SSH timeout in seconds (default: 1200)

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

CONCURRENCY="${GATE_CONCURRENCY:-3}"
DEFAULT_FLAVORS="${GATE_FLAVORS:-gnome kde cosmic niri xfce}"

command -v corral >/dev/null || { echo "corral not installed: cd ../corral && just install" >&2; exit 77; }

# ── Resolve the node pool to spread across ──────────────────────────────────
declare -a NODES=()
if [[ -n "${GATE_NODES:-}" ]]; then
    IFS=', ' read -r -a NODES <<<"${GATE_NODES}"
elif command -v kubectl >/dev/null; then
    mapfile -t NODES < <(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
fi
[[ ${#NODES[@]} -eq 0 ]] && NODES=("")  # empty string ⇒ let corral auto-schedule

# ── Expand targets into variant:flavor pairs ────────────────────────────────
declare -a PAIRS=()
for t in "$@"; do
    if [[ "$t" == *:* ]]; then
        PAIRS+=("$t")
    else
        for f in $DEFAULT_FLAVORS; do PAIRS+=("$t:$f"); done
    fi
done
[[ ${#PAIRS[@]} -eq 0 ]] && { echo "no targets given" >&2; exit 2; }

TOTAL=${#PAIRS[@]}
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  boot-gate matrix: ${TOTAL} target(s)"
echo "║  concurrency=${CONCURRENCY}  nodes=[${NODES[*]}]"
echo "╚══════════════════════════════════════════════════════════════╝"

LOGDIR="$(mktemp -d -t boot-gate-matrix.XXXXXX)"
echo "Logs: ${LOGDIR}"

# ── Launch with bounded concurrency, round-robin node assignment ────────────
declare -A PID_TARGET=()
declare -a RESULTS=()
idx=0

reap_one() {
    # Wait for any one child to finish, record its result.
    local pid
    wait -n -p pid 2>/dev/null || true
    if [[ -n "${pid:-}" && -n "${PID_TARGET[$pid]:-}" ]]; then
        local target="${PID_TARGET[$pid]}"
        local rc=0
        wait "$pid" 2>/dev/null || rc=$?
        if [[ $rc -eq 0 ]]; then RESULTS+=("✅ $target"); else RESULTS+=("❌ $target (rc=$rc)"); fi
        unset "PID_TARGET[$pid]"
    fi
}

for pair in "${PAIRS[@]}"; do
    variant="${pair%%:*}"
    flavor="${pair##*:}"
    node="${NODES[$((idx % ${#NODES[@]}))]}"
    idx=$((idx + 1))

    # Throttle: block until a slot frees up.
    while [[ ${#PID_TARGET[@]} -ge $CONCURRENCY ]]; do reap_one; done

    log="${LOGDIR}/${variant}-${flavor}.log"
    echo "→ launching ${pair}${node:+ (node=$node)}  → ${log}"
    (
        CORRAL_NODE="$node" \
        GATE_NAME="gate-${variant}-${flavor}-$$-$RANDOM" \
        GATE_TIMEOUT="${GATE_TIMEOUT:-1200}" \
        REPO_ORGANIZATION="${REPO_ORGANIZATION:-tuna-os}" \
            ./scripts/boot-gate.sh "$variant" "$flavor"
    ) >"$log" 2>&1 &
    PID_TARGET[$!]="$pair"
done

# Drain the rest.
while [[ ${#PID_TARGET[@]} -gt 0 ]]; do reap_one; done

# ── Report ──────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  boot-gate matrix results"
echo "╠══════════════════════════════════════════════════════════════╣"
fails=0
for r in "${RESULTS[@]}"; do
    printf "║  %s\n" "$r"
    [[ "$r" == ❌* ]] && fails=$((fails + 1))
done
echo "╚══════════════════════════════════════════════════════════════╝"
echo "Logs kept in ${LOGDIR}"

if [[ $fails -gt 0 ]]; then
    echo "${fails}/${TOTAL} gate(s) FAILED"
    exit 1
fi
echo "all ${TOTAL} gate(s) PASSED"
