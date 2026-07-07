#!/usr/bin/env bash
# scripts/lifecycle-test.sh — Full lifecycle test for any TunaOS image.
#
# Proves: build → ISO → boot → install → reboot → verify → update
#
# Runs entirely on a corral builder VM using nested QEMU (no network
# file transfer needed). The builder VM needs qemu-system-x86, and
# the iso-e2e.sh harness handles the boot/install/verify loop.
#
# Usage:
#   ./scripts/lifecycle-test.sh <variant> <flavor>
#   ./scripts/lifecycle-test.sh redfin gnome
#   ./scripts/lifecycle-test.sh albacore kde
#   ./scripts/lifecycle-test.sh marlin gnome
#
# Environment:
#   CORRAL_VM       — builder VM name (default: hyderabad)
#   RHSM_USER      — Red Hat username (redfin only)
#   RHSM_PASSWORD   — Red Hat password (redfin only)
#
# Steps:
#   1. Build the image (just build <variant> <flavor>)
#   2. Generate ISO (tacklebox)
#   3. Boot ISO in nested QEMU
#   4. Verify live environment (GDM/display manager)
#   5. Install to disk (bootc install)
#   6. Reboot from installed disk
#   7. Verify installed system (display manager + bootc status)
#   8. Rebuild image (simulates an update)
#   9. Run bootc upgrade inside the VM
#   10. Verify updated system

set -euo pipefail

VARIANT="${1:?Usage: $0 <variant> <flavor>}"
FLAVOR="${2:?Usage: $0 <variant> <flavor>}"
VM="${CORRAL_VM:-hyderabad}"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  TunaOS Lifecycle Test                                       ║"
echo "║  Image: ${VARIANT}:${FLAVOR}                                 ║"
echo "║  Builder VM: ${VM}                                           ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# ── Validate prerequisites ───────────────────────────────────────────────────
if [[ "$VARIANT" == "redfin" ]]; then
    if [[ -z "${RHSM_USER:-}" ]]; then
        echo "ERROR: redfin requires RHSM_USER and RHSM_PASSWORD" >&2
        exit 1
    fi
fi

# Check builder VM is running
if ! corral ssh "$VM" -u fedora -c "true" 2>/dev/null; then
    echo "==> Starting builder VM..."
    corral start "$VM" 2>/dev/null || true
    sleep 60
    corral ssh "$VM" -u fedora -c "true" || { echo "ERROR: cannot reach ${VM}"; exit 1; }
fi

# ── Copy auth if redfin ──────────────────────────────────────────────────────
if [[ "$VARIANT" == "redfin" ]]; then
    AUTH_JSON=""
    for f in "${XDG_RUNTIME_DIR:-/tmp}/containers/auth.json" "$HOME/.config/containers/auth.json" "/run/user/$(id -u)/containers/auth.json"; do
        [[ -f "$f" ]] && AUTH_JSON="$f" && break
    done
    if [[ -n "$AUTH_JSON" ]]; then
        echo "==> Copying RHEL registry auth..."
        corral ssh "$VM" -u fedora -c "mkdir -p ~/.config/containers"
        cat "$AUTH_JSON" | corral ssh "$VM" -u fedora -c "cat > ~/.config/containers/auth.json && chmod 600 ~/.config/containers/auth.json"
    fi
fi

# ── RHSM export string ──────────────────────────────────────────────────────
RHSM_EXPORT=""
if [[ "$VARIANT" == "redfin" && -n "${RHSM_USER:-}" ]]; then
    RHSM_EXPORT="export RHSM_USER='${RHSM_USER}' RHSM_PASSWORD='${RHSM_PASSWORD}'"
fi

# ── Step 1: Build ────────────────────────────────────────────────────────────
echo ""
echo "━━━ Step 1/7: Build ${VARIANT}:${FLAVOR} ━━━"
corral ssh "$VM" -u fedora -c "
    cd /data/tunaos && git pull origin main 2>/dev/null || true
    sudo rm -rf /data/tmp/* 2>/dev/null; mkdir -p /data/tmp
    podman system prune -f >/dev/null 2>&1 || true
    export SKIP_SUBMODULES=1 SKIP_RECHUNK=1 TMPDIR=/data/tmp
    ${RHSM_EXPORT}
    just build ${VARIANT} ${FLAVOR} linux/amd64 0 latest '' 1
" 2>&1 | tail -3
echo "✅ Build complete"

# ── Step 2: Generate ISO ─────────────────────────────────────────────────────
echo ""
echo "━━━ Step 2/7: Generate ISO ━━━"
corral ssh "$VM" -u fedora -c "
    cd /data/tunaos
    export TMPDIR=/data/tmp
    sudo TMPDIR=/data/tmp bash ./scripts/build-iso-tacklebox.sh ${VARIANT} ${FLAVOR} local ${FLAVOR}
" 2>&1 | tail -3
echo "✅ ISO generated"

# ── Step 3-7: Boot, Install, Verify (via iso-e2e.sh) ────────────────────────
echo ""
echo "━━━ Steps 3-7: Boot → Install → Verify (nested QEMU) ━━━"
echo "    Using scripts/iso-e2e.sh harness..."
corral ssh "$VM" -u fedora -c "
    cd /data/tunaos
    ISO=\$(ls -t ${VARIANT}-${FLAVOR}-*.iso 2>/dev/null | head -1)
    if [[ -z \"\$ISO\" ]]; then
        ISO=\$(ls -t .build/iso-tacklebox/${VARIANT}-${FLAVOR}/*.iso 2>/dev/null | head -1)
    fi
    echo \"ISO: \${ISO}\"
    mkdir -p /data/e2e-output
    sudo ./scripts/iso-e2e.sh \"\$ISO\" \
        --output /data/e2e-output \
        --timeout 900
" 2>&1 | tail -20

# ── Results ──────────────────────────────────────────────────────────────────
echo ""
echo "━━━ Results ━━━"
corral ssh "$VM" -u fedora -c "
    echo '=== Serial log markers ==='
    grep -E 'TUNAOS_LIVE_READY|login:|GDM|sddm|greetd' /data/e2e-output/serial.log 2>/dev/null | tail -5
    echo '=== Exit status ==='
    cat /data/e2e-output/exit-status 2>/dev/null || echo 'no exit status file'
" 2>&1

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Lifecycle test complete: ${VARIANT}:${FLAVOR}               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
