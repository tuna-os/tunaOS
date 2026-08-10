#!/usr/bin/env bash
# 20-nvidia.sh — install the NVIDIA driver stack on a marlin (Arch) *-nvidia
# overlay. Companion to the RPM/akmods path in overrides/nvidia/20-nvidia.sh
# (tunaOS#624: marlin/flounder/flounder-sid had no *-nvidia flavor at all).
#
# WHY nvidia-open-dkms, not nvidia-open or nvidia-dkms:
#   - nvidia-open ties the module to the EXACT `linux` package version
#     installed at transaction time (Arch's non-dkms nvidia packages rebuild
#     per point-release, like an akmods kmod). That is the exact-EVR problem
#     the RPM overlay's 10-kernel-swap.sh exists to solve for akmods; dkms
#     sidesteps it by building against whatever kernel headers are present
#     instead of requiring a pre-built binary for one exact kernel build.
#   - nvidia-dkms (the legacy proprietary DKMS package) does not exist in
#     Arch's repos any more — verified via the archweb package search API
#     (2026-08-08): only nvidia-open, nvidia-open-dkms and nvidia-open-lts
#     are published. Pre-Turing GPUs need the AUR-only 470xx/390xx legacy
#     branches, out of scope here.
#   - "open" also matches this repo's existing RPM nvidia branding
#     (ghcr.io/ublue-os/akmods-nvidia-OPEN).
#
# dkms builds against whatever /usr/lib/modules/<KVER>/build points at, not
# against the container's own running kernel — Containerfile.arch installs
# `<kernel>-headers` alongside the kernel package for exactly this, so the
# build tree is already there when this overlay runs.
#
# The exact dkms module name nvidia-open-dkms registers is NOT assumed here:
# archweb's file list for nvidia-open-dkms (2026-08-08) shows
# /usr/src/nvidia-<pkgver>/dkms.conf, so the registered name is derived from
# that directory rather than hardcoded — a point release could rename it
# without warning, and asserting a name never seen resolve is exactly what
# this repo's contract scripts avoid (see verify-nvidia.sh's header).

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

if [[ "${IS_ARCH:-false}" != "true" ]]; then
	echo "ERROR: nvidia-arch overlay ran on a non-Arch image (IS_ARCH=${IS_ARCH:-unset})." >&2
	exit 1
fi

KVER="$(basename "$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d ! -name '*.img' 2>/dev/null | sort -V | tail -1)")"
if [[ -z "$KVER" ]]; then
	echo "ERROR: no kernel module directory found under /usr/lib/modules" >&2
	exit 1
fi
echo "==> target kernel: ${KVER}"

# dkms needs a build tree for this exact kernel. Containerfile.arch installs
# <kernel-pkg>-headers alongside the kernel; a missing build symlink here
# means that pairing broke (e.g. a cachyos/-hwe parent whose headers package
# does not match this overlay's kernel), and a dkms build would silently
# fail into "nothing to build against" rather than producing a driverless
# image — fail loudly instead.
if [[ ! -e "/usr/lib/modules/${KVER}/build" ]]; then
	echo "ERROR: /usr/lib/modules/${KVER}/build is missing — dkms has no headers to build" >&2
	echo "       the nvidia module against. Expected the base image's <kernel>-headers" >&2
	echo "       package (Containerfile.arch) to provide it for ${KVER}." >&2
	exit 1
fi

pacman -Sy --noconfirm
pacman -S --noconfirm --needed \
	dkms \
	nvidia-open-dkms \
	nvidia-utils \
	nvidia-settings \
	egl-wayland \
	libva-nvidia-driver

echo "==> dkms status before build:"
dkms status || true

# Explicit build+install rather than trusting nvidia-open-dkms's pacman
# hooks to fire correctly in a container build with no running system bus —
# same reasoning as this repo's other overlays doing their own explicit
# dracut/mkinitcpio-equivalent runs instead of relying on package scriptlets
# (10-kernel-swap.sh, cachyos.sh, asahi.sh).
dkms autoinstall -k "${KVER}"

echo "==> dkms status after build:"
dkms status

# Prove the module actually landed for THIS kernel by finding the built
# file, not by string-matching dkms status output (whose module name and
# exact phrasing are not a stable contract — see header). A missing .ko
# here is a black screen on real hardware, so this is a hard failure.
NVIDIA_KO="$(find "/usr/lib/modules/${KVER}" -name 'nvidia.ko*' -print -quit)"
if [[ -z "$NVIDIA_KO" ]]; then
	echo "ERROR: dkms did not produce nvidia.ko for ${KVER} — dkms status above shows why." >&2
	exit 1
fi
echo "==> built module: ${NVIDIA_KO}"
if command -v modinfo >/dev/null 2>&1; then
	modinfo "$NVIDIA_KO" | grep -E '^(version|vermagic):' || true
fi

tee /usr/lib/modprobe.d/00-nouveau-blacklist.conf <<'EOF'
blacklist nouveau
options nouveau modeset=0
EOF

install -d /usr/lib/bootc/kargs.d
tee /usr/lib/bootc/kargs.d/00-nvidia.toml <<'EOF'
kargs = ["rd.driver.blacklist=nouveau", "modprobe.blacklist=nouveau", "nvidia-drm.modeset=1"]
EOF

# Force the driver into the initramfs. Every TunaOS bootc variant builds its
# initramfs with dracut, marlin included (Containerfile.arch's own dracut
# step) — nvidia-open-dkms ships no dracut integration of its own (it is
# Arch; mkinitcpio is the distro default, but this image never uses it), so
# this file has to be written directly, same as the RPM overlay's approach
# after its sed rewrite of the negativo17-shipped 99-nvidia.conf. i915/amdgpu
# are preloaded first so Chromium's hardware acceleration still finds an
# iGPU on hybrid-graphics laptops (same ordering as
# overrides/nvidia/20-nvidia.sh).
install -d /usr/lib/dracut/dracut.conf.d
tee /usr/lib/dracut/dracut.conf.d/99-nvidia.conf <<'EOF'
force_drivers+=" i915 amdgpu nvidia nvidia_modeset nvidia_uvm nvidia_drm "
EOF

# --tmpdir /boot: dracut defaults to /var/tmp, which is not guaranteed to
# exist when this runs outside the base image's own build (99-cleanup.sh's
# header documents the same landmine for the live-ISO rebuild path). /boot
# is always present in this stage. Positional path+kver invocation matches
# Containerfile.debian's own overlay-adjacent dracut call; compression and
# the bootc/composefs module set come from the persisted
# dracut.conf.d/30-bootc-container-build.conf the base image already wrote.
dracut --force --no-hostonly --reproducible --tmpdir /boot \
	"/usr/lib/modules/${KVER}/initramfs.img" "${KVER}"

pacman -Scc --noconfirm || true
