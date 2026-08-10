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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

VARIANT="${1:?Usage: $0 <variant> [flavor] [tag]}"
FLAVOR="${2:-gnome}"
TAG="${3:-$FLAVOR}"

ORG="${REPO_ORGANIZATION:-tuna-os}"
IMG="ghcr.io/${ORG}/${VARIANT}:${TAG}"
NAME="${GATE_NAME:-gate-${VARIANT}-${FLAVOR}-$(date +%H%M%S)}"
DISK="${GATE_DISK:-32Gi}"
TIMEOUT="${GATE_TIMEOUT:-1800}"

command -v corral >/dev/null || {
	echo "corral not installed: cd ../corral && just install" >&2
	exit 77
}
corral create --help 2>&1 | grep -q -- '--bootc' || {
	echo "corral too old (no --bootc): cd ../corral && just install" >&2
	exit 77
}

# Display manager to assert per desktop family. Space-separated candidates:
# the same DE ships different DM units per base (KDE 6.5+ renamed sddm to
# plasmalogin; xfce is lightdm on X11 bases and greetd on the Wayland ones).
# Any one active counts as a pass.
case "$FLAVOR" in
kde*) DM="sddm plasmalogin" ;; cosmic*) DM="greetd cosmic-greeter" ;; niri*) DM=greetd ;; xfce*) DM="lightdm greetd gdm" ;; *) DM="gdm gdm3" ;;
esac

NODE_ARGS=()
[[ -n "${CORRAL_NODE:-}" ]] && NODE_ARGS=(--node "${CORRAL_NODE}")

cleanup() { corral delete "$NAME" -f >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> boot-gate ${IMG}  (vm=${NAME}${CORRAL_NODE:+ node=$CORRAL_NODE})"
if ! corral create "$NAME" --bootc "$IMG" --disk "$DISK" --wait-ssh --timeout "$TIMEOUT" "${NODE_ARGS[@]}"; then
	# tuna-os/tunaOS#627: KubeVirt virt-launcher teardown can destroy the
	# builder's serial log before corral reads the build-success marker, so a
	# build that actually finished reports "builder VM ended (Succeeded)
	# without a build marker" (the disk-size fallback has the same race via a
	# separate size-check pod). The disk PVC is valid — resume the build from
	# the completed disk instead of failing the gate. --resume errors cleanly
	# when there is genuinely nothing to resume (no completed builder + disk
	# PVC), so attempting it on any bootc-build failure is safe.
	echo "==> corral build failed; attempting --resume from the completed disk (#627)"
	if ! corral bootc create "$NAME" --image "$IMG" --resume "${NODE_ARGS[@]}"; then
		echo "FAIL: bootc build failed and no resumable build was found" >&2
		exit 1
	fi
	corral start "$NAME"
	# --resume finishes the VM but does not start it or wait for SSH;
	# replicate the --wait-ssh loop from the main CLI.
	ssh_ok=0
	for _ in $(seq 1 $((TIMEOUT / 10))); do
		if corral ssh "$NAME" -u root -c true 2>/dev/null; then
			ssh_ok=1
			break
		fi
		sleep 10
	done
	[[ "$ssh_ok" == 1 ]] || {
		echo "FAIL: SSH not reachable after --resume (timeout ${TIMEOUT}s)" >&2
		exit 1
	}
fi

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
[[ "$(check 'systemctl is-active graphical.target' | tr -d '[:space:]')" == active ]] || {
	echo "FAIL graphical.target"
	RC=1
}
DM_OK=0
for _dm in $DM; do
	if [[ "$(check "systemctl is-active ${_dm}" | tr -d '[:space:]')" == active ]]; then
		DM_OK=1
		echo "ok display-manager: ${_dm}"
		break
	fi
done
[[ "$DM_OK" == 1 ]] || {
	echo "FAIL display manager (tried: $DM)"
	RC=1
}
check 'systemctl --failed --no-legend' || true
check 'bootc status --format json' | jq -r '.status.booted.image.image.image' 2>/dev/null || true

# ── Tier-1 functional checks (advisory) — tuna-os/tunaos#576 ────────────────
# tests/functional/run.sh is the shared dispatcher (same checks CI, corral,
# and manual runs use) — it covers more than the ad-hoc checks above: the
# failed-unit allowlist (vs. just listing them), session binary + session
# entry, Flathub, and (with VARIANT) branding. Run it here for visibility
# while the suite proves itself stable; it does NOT affect $RC yet — per the
# issue's phased rollout this starts advisory and flips blocking once there
# is a track record. FLAVOR can carry an overlay suffix (gnome-nvidia,
# kde-hwe, ...) that run.sh's dispatcher does not know about; strip it down
# to the bare desktop name it expects. base* flavors have no desktop to
# check and are skipped, same as the boot gate in reusable-build-image.yml.
FUNC_DESKTOP="$FLAVOR"
for _suffix in -nvidia-hwe -nvidia -hwe -cachyos -asahi -zfs; do
	if [[ "$FUNC_DESKTOP" == *"$_suffix" ]]; then
		FUNC_DESKTOP="${FUNC_DESKTOP%"$_suffix"}"
		break
	fi
done
if [[ "$FUNC_DESKTOP" != base* ]]; then
	echo "==> tier-1 functional checks (advisory): ${FUNC_DESKTOP}"
	if corral ssh "$NAME" -u root -c "bash -s ${FUNC_DESKTOP} ${VARIANT}" \
		<"${REPO_ROOT}/tests/functional/run.sh"; then
		echo "✅ functional checks PASS (advisory)"
	else
		echo "⚠️  functional checks reported failures (advisory — not blocking yet)"
	fi
fi

if [[ $RC -eq 0 ]]; then
	echo "✅ boot-gate PASS: $IMG"
else
	echo "❌ boot-gate FAIL: $IMG"
fi
exit $RC
