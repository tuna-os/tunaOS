#!/usr/bin/env bash
# scripts/boot-gate.sh — Boot-gate one published (or local) image via corral.
#
# Builds a bootc disk, boots it (KubeVirt when the cluster is reachable, local
# QEMU otherwise), waits for SSH, then runs the tier-1 desktop health checks.
# One command, same behavior locally and in CI.
#
# Usage:
#   scripts/boot-gate.sh <variant> [flavor] [tag]
#
# Environment:
#   REPO_ORGANIZATION  — GHCR org (default: tuna-os)
#   CORRAL_NODE        — schedule the gate VM on this KubeVirt node (default: auto)
#   GATE_DISK          — disk size (default: 32Gi)
#   GATE_TIMEOUT       — seconds to wait for SSH (default: 1200)
#   GATE_NAME          — override the VM name (default: gate-<variant>-<flavor>-<time>)

set -euo pipefail

VARIANT="${1:?Usage: $0 <variant> [flavor] [tag]}"
FLAVOR="${2:-gnome}"
TAG="${3:-$FLAVOR}"

ORG="${REPO_ORGANIZATION:-tuna-os}"
IMG="ghcr.io/${ORG}/${VARIANT}:${TAG}"
NAME="${GATE_NAME:-gate-${VARIANT}-${FLAVOR}-$(date +%H%M%S)}"
DISK="${GATE_DISK:-32Gi}"
TIMEOUT="${GATE_TIMEOUT:-1200}"

command -v corral >/dev/null || { echo "corral not installed: cd ../corral && just install" >&2; exit 77; }
corral create --help 2>&1 | grep -q -- '--bootc' || { echo "corral too old (no --bootc): cd ../corral && just install" >&2; exit 77; }

# Display manager to assert per desktop family.
case "$FLAVOR" in
    kde*) DM=sddm ;; niri* | cosmic*) DM=greetd ;; xfce*) DM=lightdm ;; *) DM=gdm ;;
esac

NODE_ARGS=()
[[ -n "${CORRAL_NODE:-}" ]] && NODE_ARGS=(--node "${CORRAL_NODE}")

cleanup() { corral delete "$NAME" -f >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> boot-gate ${IMG}  (vm=${NAME}${CORRAL_NODE:+ node=$CORRAL_NODE})"
corral create "$NAME" --bootc "$IMG" --disk "$DISK" --wait-ssh --timeout "$TIMEOUT" "${NODE_ARGS[@]}"

check() { corral ssh "$NAME" -u root -c "$1"; }

# Give the desktop a moment to finish activating after SSH answers —
# graphical.target (GDM/SDDM) can take 30-60s longer than sshd on virtual
# hardware without GPU acceleration.
for i in 1 2 3 4 5 6; do
    STATE=$(check 'systemctl is-active graphical.target' 2>/dev/null | tr -d '[:space:]')
    [[ "$STATE" == "active" ]] && break
    sleep 10
done

RC=0
[[ "$(check 'systemctl is-active graphical.target' | tr -d '[:space:]')" == active ]] || { echo "FAIL graphical.target"; RC=1; }
[[ "$(check "systemctl is-active $DM" | tr -d '[:space:]')" == active ]] || { echo "FAIL $DM"; RC=1; }
check 'systemctl --failed --no-legend' || true
check 'bootc status --format json' | jq -r '.status.booted.image.image.image' 2>/dev/null || true

if [[ $RC -eq 0 ]]; then
    echo "✅ boot-gate PASS: $IMG"
else
    echo "❌ boot-gate FAIL: $IMG"
fi
exit $RC
