#!/usr/bin/env bash
# scripts/iso-e2e-gpu.sh — run iso-e2e.sh inside a GPU-capable container.
#
# WHY THIS EXISTS
#
# cosmic, niri and xfwl4 are Smithay compositors. They hard-require
# EGL_EXT_device_drm, which QEMU's plain `-vga virtio` does not expose, and
# there is no software fallback — the compositor simply never starts. On a
# GPU-less GitHub runner that surfaces as:
#
#   greetd: check_children: greeter exited without creating a session
#   greetd.service: Failed with result 'start-limit-hit'
#   libEGL: failed to create dri2 screen          (cosmic)
#
# so the installer can never be asserted, no matter what the installer does.
# Three of the four desktops in installer-smoke fail this way and always will
# on hosted runners.
#
# iso-e2e.sh already does the right thing on its own: it auto-selects
# `virtio-vga-gl + egl-headless,rendernode=/dev/dri/renderD128` whenever a DRM
# render node exists. It needs no changes. What it needs is a HOST that has
# one. This script is that host adapter — it supplies qemu + OVMF + the GL
# subpackages in a container, passing the real render node and KVM through.
#
# Hosts like himachal have the render node and KVM but a read-only composefs
# root with no qemu, so installing qemu on the host is not an option; a
# container is.
#
# USAGE
#
#   scripts/iso-e2e-gpu.sh <iso_path> [iso-e2e.sh args...]
#
# All arguments after the ISO are forwarded to iso-e2e.sh verbatim, so
# --ssh-only / --luks / --app-launch / --output all work as usual:
#
#   scripts/iso-e2e-gpu.sh out.iso --ssh-only --keep-vm --output smoke-out
#
# ENVIRONMENT
#
#   TBOX_E2E_RENDERNODE  DRM render node to pass through (default
#                        /dev/dri/renderD128)
#   TBOX_E2E_IMAGE       container image to build/use (default
#                        localhost/tunaos-e2e-gpu:latest)
#   TBOX_E2E_REBUILD=1   force a rebuild of the container image
#
# VERIFYING THE HOST IS ACTUALLY CAPABLE
#
# A host passes only if BOTH of these hold inside the container — checked
# below before any ISO is booted, because a silent fall back to software
# rendering would reproduce the exact GPU-less failure this exists to avoid:
#
#   qemu-system-x86_64 -device help    | grep virtio-vga-gl
#   qemu-system-x86_64 -display help   | grep egl-headless
#
# Fedora splits these out of qemu-system-x86-core: virtio-vga-gl needs BOTH
# qemu-device-display-virtio-vga-gl and qemu-device-display-virtio-gpu-gl
# (the former alone fails at runtime with "missing object type
# 'virtio-gpu-gl-device'"), and egl-headless needs qemu-ui-egl-headless.

set -euo pipefail

RENDERNODE="${TBOX_E2E_RENDERNODE:-/dev/dri/renderD128}"
IMAGE="${TBOX_E2E_IMAGE:-localhost/tunaos-e2e-gpu:latest}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -lt 1 ]]; then
	sed -n '2,60p' "${BASH_SOURCE[0]}" >&2
	exit 2
fi
ISO="$1"
shift

[[ -f "$ISO" ]] || {
	echo "ERROR: no such ISO: $ISO" >&2
	exit 2
}
# The container runs iso-e2e.sh out of the bind-mounted repo, so a partial
# copy of just this script fails deep inside podman with an opaque "executable
# file not found". Catch it here instead.
[[ -x "$REPO_ROOT/scripts/iso-e2e.sh" ]] || {
	echo "ERROR: $REPO_ROOT/scripts/iso-e2e.sh not found or not executable." >&2
	echo "       This script runs iso-e2e.sh from the repo it lives in — run it" >&2
	echo "       from a full tunaOS checkout, not a copy of this file alone." >&2
	exit 2
}
[[ -e "$RENDERNODE" ]] || {
	echo "ERROR: no DRM render node at $RENDERNODE — this host cannot run the" >&2
	echo "       Smithay compositors (cosmic/niri/xfwl4). Use a host with a GPU," >&2
	echo "       or run scripts/iso-e2e.sh directly and accept blank frames." >&2
	exit 77
}
[[ -e /dev/kvm ]] || echo "WARNING: no /dev/kvm — falling back to TCG, expect this to be slow" >&2

command -v podman >/dev/null || {
	echo "ERROR: podman required" >&2
	exit 77
}

# Build the harness image if absent. Pinned to the packages iso-e2e.sh
# actually shells out to (qemu-img, socat, sshpass, swtpm, python3) plus the
# GL/UI subpackages above.
if [[ "${TBOX_E2E_REBUILD:-}" == "1" ]] || ! podman image exists "$IMAGE"; then
	echo "==> building $IMAGE"
	podman build -t "$IMAGE" -f - "$REPO_ROOT" <<'CONTAINERFILE'
FROM registry.fedoraproject.org/fedora:41
# vncdotool: screendump cannot capture a virgl guest once a Wayland
# compositor scans out through GL ("Error: no surface"), so the VNC client
# path in iso-e2e.sh's screenshot() is the only way to get an image of the
# very sessions this GPU harness exists to test.
RUN dnf -y install --setopt=install_weak_deps=False \
      qemu-system-x86-core \
      qemu-img \
      edk2-ovmf \
      qemu-ui-egl-headless \
      qemu-device-display-virtio-vga-gl \
      qemu-device-display-virtio-gpu-gl \
      virglrenderer \
      mesa-dri-drivers \
      mesa-libEGL \
      socat sshpass swtpm swtpm-tools python3 python3-pip openssh-clients \
      bash coreutils util-linux procps-ng \
 && python3 -m pip install --no-cache-dir vncdotool \
 && dnf clean all
CONTAINERFILE
fi

# Capability gate. Failing here is far better than booting an ISO and
# spending 20 minutes to discover the compositor never started.
echo "==> verifying container GPU capability"
caps=$(podman run --rm --device "$RENDERNODE" "$IMAGE" bash -c '
  d=$(qemu-system-x86_64 -device help 2>/dev/null | grep -c "virtio-vga-gl" || true)
  e=$(qemu-system-x86_64 -display help 2>/dev/null | grep -c "egl-headless" || true)
  echo "$d $e"')
read -r have_dev have_display <<<"$caps"
if [[ "$have_dev" -lt 1 || "$have_display" -lt 1 ]]; then
	echo "ERROR: harness image lacks GL support (virtio-vga-gl=$have_dev egl-headless=$have_display)." >&2
	echo "       Rebuild with TBOX_E2E_REBUILD=1." >&2
	exit 1
fi
echo "==> GPU capability confirmed (virtio-vga-gl + egl-headless)"

ISO_ABS="$(cd "$(dirname "$ISO")" && pwd)/$(basename "$ISO")"

# --privileged: iso-e2e.sh runs parts of itself under sudo and manages
# swtpm sockets. Network is host so the script's port-2222 SSH forward and
# QEMU monitor socket behave exactly as they do on a bare host.
# Only allocate a TTY when we have one — under CI/ssh without a tty, podman
# warns and can misbehave.
TTY_ARGS=()
[[ -t 0 && -t 1 ]] && TTY_ARGS=(-it)

exec podman run --rm "${TTY_ARGS[@]}" \
	--device /dev/kvm \
	--device "$RENDERNODE" \
	--privileged \
	--network host \
	-v "$REPO_ROOT:$REPO_ROOT:z" \
	-v "$ISO_ABS:$ISO_ABS:z" \
	-w "$REPO_ROOT" \
	-e "TBOX_E2E_GPU=${TBOX_E2E_GPU:-virgl}" \
	-e "FLAVOR=${FLAVOR:-}" \
	-e "VARIANT=${VARIANT:-}" \
	"$IMAGE" \
	./scripts/iso-e2e.sh "$ISO_ABS" "$@"
