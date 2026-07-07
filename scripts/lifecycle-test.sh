#!/usr/bin/env bash
# scripts/lifecycle-test.sh — Full lifecycle test with timeouts and timing.
#
# Usage:
#   ./scripts/lifecycle-test.sh <variant> <flavor>
#
# Timeouts (override via env):
#   BUILD_TIMEOUT=1200    — image build (default: 20 min)
#   ISO_TIMEOUT=300       — ISO generation (default: 5 min)
#   BOOT_TIMEOUT=600      — QEMU boot + verify (default: 10 min)

set -euo pipefail

VARIANT="${1:?Usage: $0 <variant> <flavor>}"
FLAVOR="${2:?Usage: $0 <variant> <flavor>}"
VM="${CORRAL_VM:-hyderabad}"

BUILD_TIMEOUT="${BUILD_TIMEOUT:-1200}"
ISO_TIMEOUT="${ISO_TIMEOUT:-300}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-600}"

# Timing helper
_time() {
    local label=$1; shift
    local start=$(date +%s)
    if "$@"; then
        local elapsed=$(($(date +%s) - start))
        printf "  ✅ %s (%ds)\n" "$label" "$elapsed"
        return 0
    else
        local elapsed=$(($(date +%s) - start))
        printf "  ❌ %s FAILED (%ds)\n" "$label" "$elapsed"
        return 1
    fi
}

# SSH with timeout
_ssh() {
    local timeout=$1; shift
    timeout "${timeout}" corral ssh "$VM" -u fedora -c "$*" 2>/dev/null
}

echo "╔══════════════════════════════════════════════════════╗"
echo "║  Lifecycle: ${VARIANT}:${FLAVOR}                     ║"
echo "║  Timeouts: build=${BUILD_TIMEOUT}s iso=${ISO_TIMEOUT}s boot=${BOOT_TIMEOUT}s ║"
echo "╚══════════════════════════════════════════════════════╝"

# Validate
if [[ "$VARIANT" == "redfin" && -z "${RHSM_USER:-}" ]]; then
    echo "ERROR: RHSM_USER required for redfin" >&2; exit 1
fi

# Auth
if [[ "$VARIANT" == "redfin" ]]; then
    AUTH_JSON=""
    for f in "${XDG_RUNTIME_DIR:-/tmp}/containers/auth.json" "$HOME/.config/containers/auth.json" "/run/user/$(id -u)/containers/auth.json"; do
        [[ -f "$f" ]] && AUTH_JSON="$f" && break
    done
    [[ -n "$AUTH_JSON" ]] && cat "$AUTH_JSON" | corral ssh "$VM" -u fedora -c "mkdir -p ~/.config/containers && cat > ~/.config/containers/auth.json && chmod 600 ~/.config/containers/auth.json" 2>/dev/null
fi

RHSM_EXPORT=""
[[ "$VARIANT" == "redfin" ]] && RHSM_EXPORT="export RHSM_USER='${RHSM_USER}' RHSM_PASSWORD='${RHSM_PASSWORD}'"

TOTAL_START=$(date +%s)

# ── Step 1: Build ────────────────────────────────────────────────────────────
echo ""
echo "━━━ Step 1: Build (timeout: ${BUILD_TIMEOUT}s) ━━━"
_time "Build ${VARIANT}:${FLAVOR}" \
    _ssh "$BUILD_TIMEOUT" "
        cd /data/tunaos && git pull origin main 2>/dev/null || true
        sudo rm -rf /data/tmp/* 2>/dev/null; mkdir -p /data/tmp
        podman system prune -f >/dev/null 2>&1 || true
        export SKIP_SUBMODULES=1 SKIP_RECHUNK=1 TMPDIR=/data/tmp
        ${RHSM_EXPORT}
        just build ${VARIANT} ${FLAVOR} linux/amd64 0 latest '' 1
    " || exit 1

# ── Step 2: ISO ──────────────────────────────────────────────────────────────
echo ""
echo "━━━ Step 2: ISO (timeout: ${ISO_TIMEOUT}s) ━━━"
_time "Generate ISO" \
    _ssh "$ISO_TIMEOUT" "
        cd /data/tunaos
        export TMPDIR=/data/tmp
        sudo TMPDIR=/data/tmp bash ./scripts/build-iso-tacklebox.sh ${VARIANT} ${FLAVOR} local ${FLAVOR}
    " || exit 1

# ── Step 3: Boot + Verify ────────────────────────────────────────────────────
echo ""
echo "━━━ Step 3: Boot + Verify (timeout: ${BOOT_TIMEOUT}s) ━━━"
_time "ISO boot → GDM → TUNAOS_LIVE_READY" \
    _ssh "$BOOT_TIMEOUT" "
        cd /data/tunaos
        ISO=\$(ls -t ${VARIANT}-${FLAVOR}-*.iso 2>/dev/null | head -1)
        mkdir -p /data/e2e-output
        sudo ./scripts/iso-e2e.sh \"\$ISO\" --output /data/e2e-output --timeout 300
    " || exit 1

# ── Summary ──────────────────────────────────────────────────────────────────
TOTAL_ELAPSED=$(($(date +%s) - TOTAL_START))
echo ""
echo "╔══════════════════════════════════════════════════════╗"
printf "║  ✅ PASSED: %-38s  ║\n" "${VARIANT}:${FLAVOR}"
printf "║  Total: %ds                                       ║\n" "$TOTAL_ELAPSED"
echo "╚══════════════════════════════════════════════════════╝"
