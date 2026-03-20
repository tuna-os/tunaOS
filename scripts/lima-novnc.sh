#!/usr/bin/env bash
# Start a Lima VM from a qcow2 or live ISO, then wire up a noVNC container.
#
# Usage: scripts/lima-novnc.sh <vm_name> <type> <image_path>

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VM_NAME="${1:-}"
TYPE="${2:-}"
IMAGE_PATH="${3:-}"

if ! command -v limactl &>/dev/null; then
	echo "Error: 'limactl' not found. Install Lima: https://lima-vm.io/"
	exit 1
fi

ARCH=$(uname -m)
[[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && LIMA_ARCH="aarch64" || LIMA_ARCH="x86_64"

# Remove any pre-existing VM with this name
if limactl list -q 2>/dev/null | grep -q "^${VM_NAME}$"; then
	echo "==> Removing existing VM: ${VM_NAME}"
	limactl stop -f "${VM_NAME}" 2>/dev/null || true
	limactl delete "${VM_NAME}"
fi

CONFIG_FILE=$(mktemp --suffix=.yaml)
CLEANUP_FILES=("${CONFIG_FILE}")
trap 'rm -f "${CLEANUP_FILES[@]}" 2>/dev/null || true' EXIT

if [[ "${TYPE}" == "iso" ]]; then
	# Create a sparse target disk; QEMU boots from the ISO via -cdrom
	EMPTY_DISK=$(mktemp --suffix=.qcow2)
	CLEANUP_FILES+=("${EMPTY_DISK}")
	qemu-img create -f qcow2 "${EMPTY_DISK}" 32G

	# plain=true skips SSH/cloud-init checks so Lima doesn't block waiting for a live OS
	{
		echo "images:"
		echo "  - location: ${EMPTY_DISK}"
		echo "    arch: ${LIMA_ARCH}"
		echo "video:"
		echo "  display: \"vnc\""
		echo "memory: \"4GiB\""
		echo "cpus: 4"
		echo "plain: true"
		echo "qemu:"
		echo "  extraArgs:"
		echo "    - \"-cdrom\""
		echo "    - ${IMAGE_PATH}"
		echo "    - \"-boot\""
		echo "    - \"order=d,menu=on\""
	} >"${CONFIG_FILE}"
else
	# qcow2: boot directly; plain=true because bootc images may not have cloud-init
	{
		echo "images:"
		echo "  - location: ${IMAGE_PATH}"
		echo "    arch: ${LIMA_ARCH}"
		echo "video:"
		echo "  display: \"vnc\""
		echo "memory: \"4GiB\""
		echo "cpus: 4"
		echo "plain: true"
	} >"${CONFIG_FILE}"
fi

echo "==> Starting Lima VM: ${VM_NAME}"
limactl start --name="${VM_NAME}" --tty=false "${CONFIG_FILE}"

# Resolve VNC host:port — Lima writes the QEMU display string to vncdisplay
VNC_DISPLAY=""
VNC_DISPLAY=$(limactl list --json 2>/dev/null | jq -r "select(.name==\"${VM_NAME}\") | .video.vnc.display // empty" || true)
if [[ -z "${VNC_DISPLAY}" ]]; then
	VNC_FILE="${HOME}/.lima/${VM_NAME}/vncdisplay"
	[[ -f "${VNC_FILE}" ]] && VNC_DISPLAY=$(cat "${VNC_FILE}")
fi

if [[ -z "${VNC_DISPLAY}" ]]; then
	echo "Error: could not determine VNC display for ${VM_NAME}."
	echo "Check: ls ~/.lima/${VM_NAME}/"
	exit 1
fi

VNC_DISPLAY="${VNC_DISPLAY%%,*}" # strip trailing options like ",to=9"
VNC_HOST="${VNC_DISPLAY%:*}"
VNC_DISP_NUM="${VNC_DISPLAY##*:}"
VNC_PORT=$((5900 + VNC_DISP_NUM))

# Lima generates a VNC password stored alongside the display file
VNC_PASS_FILE="${HOME}/.lima/${VM_NAME}/vncpassword"
VNC_PASS=""
[[ -f "${VNC_PASS_FILE}" ]] && VNC_PASS=$(cat "${VNC_PASS_FILE}")

# Find a free port for the noVNC web UI
NOVNC_PORT=6080
while ss -tln 2>/dev/null | grep -q ":${NOVNC_PORT} "; do
	NOVNC_PORT=$((NOVNC_PORT + 1))
done

echo "==> VNC at ${VNC_HOST}:${VNC_PORT}"
echo "==> Starting noVNC on port ${NOVNC_PORT}..."

# Remove any leftover noVNC container from a previous run
podman rm -f "${VM_NAME}-novnc" 2>/dev/null || true

# ghcr.io/novnc/novnc ships novnc_proxy (websockify wrapper + static files).
# --network host lets the container reach Lima's VNC on 127.0.0.1.
podman run -d --rm \
	--name "${VM_NAME}-novnc" \
	--network host \
	ghcr.io/novnc/novnc:latest \
	/usr/share/novnc/utils/novnc_proxy \
	--listen "${NOVNC_PORT}" \
	--vnc "${VNC_HOST}:${VNC_PORT}"

# Build the local URL; embed password so the browser connects automatically
NOVNC_PARAMS="vnc.html?autoconnect=1"
[[ -n "${VNC_PASS}" ]] && NOVNC_PARAMS="${NOVNC_PARAMS}&password=${VNC_PASS}"
LOCAL_URL="http://127.0.0.1:${NOVNC_PORT}/${NOVNC_PARAMS}&host=127.0.0.1&port=${NOVNC_PORT}"

# Detect Tailscale IP for remote access
TAILSCALE_IP=""
if command -v tailscale &>/dev/null; then
	TAILSCALE_IP=$(tailscale ip -4 2>/dev/null | head -1 || true)
fi
if [[ -z "${TAILSCALE_IP}" ]]; then
	TAILSCALE_IP=$(ip addr show tailscale0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -1 || true)
fi

echo "==> Waiting for noVNC to be ready..."
for _i in {1..20}; do
	if curl -sf "http://127.0.0.1:${NOVNC_PORT}/" &>/dev/null; then
		break
	fi
	sleep 1
done

echo ""
echo "=============================="
echo " VM:       ${VM_NAME}"
echo " Local:    ${LOCAL_URL}"
if [[ -n "${TAILSCALE_IP}" ]]; then
	TAILNET_URL="http://${TAILSCALE_IP}:${NOVNC_PORT}/${NOVNC_PARAMS}&host=${TAILSCALE_IP}&port=${NOVNC_PORT}"
	echo " Tailnet:  ${TAILNET_URL}"
fi
[[ -n "${VNC_PASS}" ]] && echo " Password: ${VNC_PASS}"
echo "=============================="
echo " Stop: limactl stop ${VM_NAME} && podman stop ${VM_NAME}-novnc"
echo ""

if command -v xdg-open &>/dev/null; then
	xdg-open "${LOCAL_URL}" || true
fi
