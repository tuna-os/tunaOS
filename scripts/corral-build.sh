#!/usr/bin/env bash
# scripts/corral-build.sh — Build TunaOS images on a corral builder VM.
#
# Provisions a builder VM (if needed), copies auth credentials, clones
# the repo, and fans out the build matrix. Each flavor builds sequentially
# on the VM (parallel would OOM on a single node).
#
# Usage:
#   ./scripts/corral-build.sh <variant> [flavors...]
#   ./scripts/corral-build.sh redfin gnome kde niri cosmic xfce
#   ./scripts/corral-build.sh redfin all
#   ./scripts/corral-build.sh yellowfin gnome  # non-RHEL variants too
#
# Prerequisites:
#   - corral CLI installed and connected to a KubeVirt cluster
#   - podman logged into registry.redhat.io (for redfin)
#   - tunaos-builder.yaml in the repo root
#
# Environment:
#   CORRAL_VM       — VM name (default: tunaos-builder)
#   CORRAL_NODE     — schedule on this node (default: auto)
#   CORRAL_BRANCH   — git branch to build from (default: main)
#   SKIP_RECHUNK    — skip chunkah rechunking (default: 1 for local builds)
#   RHSM_USER      — Red Hat username (redfin only, read from env or auth.json)
#   RHSM_PASSWORD   — Red Hat password (redfin only)

set -euo pipefail

VARIANT="${1:?Usage: $0 <variant> [flavors...]}"
shift
FLAVORS=("${@:-gnome}")

# Expand "all" to the full desktop list
if [[ "${FLAVORS[0]}" == "all" ]]; then
    FLAVORS=(gnome kde niri cosmic xfce)
fi

VM="${CORRAL_VM:-tunaos-builder}"
NODE="${CORRAL_NODE:-karnataka}"
BRANCH="${CORRAL_BRANCH:-main}"
SKIP_RECHUNK="${SKIP_RECHUNK:-1}"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  TunaOS Corral Build                                        ║"
echo "║  Variant: ${VARIANT}                                        ║"
echo "║  Flavors: ${FLAVORS[*]}                                     ║"
echo "║  VM: ${VM} (node: ${NODE})                                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# ── Ensure the builder VM exists and is running ──────────────────────────────
if ! corral list 2>/dev/null | grep -q "^${VM}"; then
    echo "==> Creating builder VM from tunaos-builder.yaml..."
    corral create "$VM" -f ./tunaos-builder.yaml --node "$NODE"
fi

VM_STATUS=$(corral list 2>/dev/null | grep "^${VM}" | awk '{print $3}')
if [[ "$VM_STATUS" != "●" ]]; then
    echo "==> Starting builder VM..."
    corral start "$VM"
    echo "    Waiting for boot + provisioning (90s)..."
    sleep 90
fi

# Wait for SSH
for i in 1 2 3 4 5; do
    corral ssh "$VM" -u fedora -c "true" 2>/dev/null && break
    echo "    Waiting for SSH... ($i/5)"
    sleep 15
done

# ── Copy registry auth (for RHEL/redfin) ────────────────────────────────────
AUTH_JSON=""
for f in "${XDG_RUNTIME_DIR:-/tmp}/containers/auth.json" "$HOME/.config/containers/auth.json" "/run/user/$(id -u)/containers/auth.json"; do
    [[ -f "$f" ]] && AUTH_JSON="$f" && break
done

if [[ -n "$AUTH_JSON" ]]; then
    echo "==> Copying registry auth to builder..."
    corral ssh "$VM" -u fedora -c "mkdir -p ~/.config/containers"
    cat "$AUTH_JSON" | corral ssh "$VM" -u fedora -c "cat > ~/.config/containers/auth.json && chmod 600 ~/.config/containers/auth.json"
    # Also for root (needed for ISO builds)
    cat "$AUTH_JSON" | corral ssh "$VM" -u root -c "mkdir -p /run/containers/0 && cat > /run/containers/0/auth.json && chmod 600 /run/containers/0/auth.json" 2>/dev/null || true
fi

# ── Clone/update the repo on the builder ─────────────────────────────────────
echo "==> Syncing repo (branch: ${BRANCH})..."
corral ssh "$VM" -u fedora -c "
    test -d /data/tunaos/.git || git -C /data clone --depth 1 https://github.com/tuna-os/tunaOS.git tunaos
    cd /data/tunaos && git fetch origin && git checkout origin/${BRANCH} 2>/dev/null || git checkout ${BRANCH}
    git pull origin ${BRANCH} 2>/dev/null || true
"

# ── Build each flavor ────────────────────────────────────────────────────────
RESULTS=()
for flavor in "${FLAVORS[@]}"; do
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Building: ${VARIANT}:${flavor}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    BUILD_START=$(date +%s)

    # Pass RHSM creds if set locally
    RHSM_EXPORT=""
    if [[ -n "${RHSM_USER:-}" ]]; then
        RHSM_EXPORT="export RHSM_USER='${RHSM_USER}' RHSM_PASSWORD='${RHSM_PASSWORD}'"
    fi

    if corral ssh "$VM" -u fedora -c "
        cd /data/tunaos
        export SKIP_SUBMODULES=1 SKIP_RECHUNK=${SKIP_RECHUNK}
        ${RHSM_EXPORT}
        just build ${VARIANT} ${flavor} linux/amd64 0 latest '' 1
    " 2>&1 | tee "/tmp/corral-build-${VARIANT}-${flavor}.log" | tail -3; then
        BUILD_SECS=$(($(date +%s) - BUILD_START))
        RESULTS+=("✅ ${VARIANT}:${flavor} (${BUILD_SECS}s)")
        echo "  ✅ ${VARIANT}:${flavor} built in ${BUILD_SECS}s"
    else
        BUILD_SECS=$(($(date +%s) - BUILD_START))
        RESULTS+=("❌ ${VARIANT}:${flavor} (${BUILD_SECS}s)")
        echo "  ❌ ${VARIANT}:${flavor} FAILED after ${BUILD_SECS}s"
        echo "     Log: /tmp/corral-build-${VARIANT}-${flavor}.log"
    fi
done

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Build Results                                              ║"
echo "╠══════════════════════════════════════════════════════════════╣"
for r in "${RESULTS[@]}"; do
    printf "║  %-56s  ║\n" "$r"
done
echo "╚══════════════════════════════════════════════════════════════╝"

# ── Optional: create corral bootc VMs from built images ──────────────────────
echo ""
echo "To test a built image in a VM:"
echo "  corral ssh ${VM} -u fedora -c 'podman images | grep ${VARIANT}'"
echo "  # Then push to a local registry or use corral bootc create"
