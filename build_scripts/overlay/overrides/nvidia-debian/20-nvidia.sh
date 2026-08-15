#!/usr/bin/env bash
# 20-nvidia.sh — install the NVIDIA driver stack on a flounder/flounder-sid
# (Debian) *-nvidia overlay. Companion to the RPM/akmods path in
# overrides/nvidia/20-nvidia.sh and the Arch path in
# overrides/nvidia-arch/20-nvidia.sh (tunaOS#624).
#
# Package source: the OFFICIAL Debian archive, non-free component — NOT a
# third-party repo (unlike overlay/asahi.sh's debian branch, which needs the
# Bananas team's side archive for a kernel Debian does not ship). Verified
# against the live archive via madison (2026-08-08):
#   nvidia-driver 550.163.01-2   in stable/non-free   (flounder  = trixie)
#   nvidia-driver 550.163.01-5.1 in unstable/non-free (flounder-sid = sid)
# nvidia-kernel-dkms, nvidia-driver-libs, nvidia-vulkan-icd and dkms itself
# are all in the same archive, so nothing here needs a new signing key or
# sources file — only enabling components already-present sources.list(.d)
# entries don't turn on by default.
#
# dkms builds against whatever kernel headers are present, not the
# container's own running kernel: Containerfile.debian's linux-image-generic
# is a virtual package resolving to linux-image-amd64 (verified via
# packages.debian.org, 2026-08-08), and linux-headers-generic resolves to
# the matching linux-headers-amd64 the SAME way — both are kept in lockstep
# by the linux source package, so installing them together always pairs a
# kernel with its own headers, no exact-EVR juggling required.
#
# The exact dkms module name nvidia-kernel-dkms registers is NOT assumed:
# the Debian Contents index (2026-08-08) shows
# /usr/src/nvidia-current-<version>/Kbuild, so the registered name is
# derived from that directory rather than hardcoded — see the module-name
# note in overrides/nvidia-arch/20-nvidia.sh for why.

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

if [[ "${IS_DEBIAN:-false}" != "true" ]]; then
	echo "ERROR: nvidia-debian overlay ran on a non-Debian image (IS_DEBIAN=${IS_DEBIAN:-unset})." >&2
	exit 1
fi

KVER="$(basename "$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d ! -name '*.img' 2>/dev/null | sort -V | tail -1)")"
if [[ -z "$KVER" ]]; then
	echo "ERROR: no kernel module directory found under /usr/lib/modules" >&2
	exit 1
fi
echo "==> target kernel: ${KVER}"

# Enable contrib/non-free/non-free-firmware on whatever debian.org source
# file(s) the base image ships, without assuming a filename: Debian's
# official Docker images have used the deb822 debian.sources format since
# bookworm, but probing rather than hardcoding the path survives that
# changing again the way it already has once. A legacy one-line
# /etc/apt/sources.list, if present instead, is handled the same way.
_found_components=0
for f in /etc/apt/sources.list.d/*.sources; do
	[[ -f "$f" ]] || continue
	if grep -qE '^Components:' "$f"; then
		sed -i -E 's/^(Components:.*)$/\1 contrib non-free non-free-firmware/' "$f"
		_found_components=1
	fi
done
if [[ -f /etc/apt/sources.list ]] && grep -qE '^deb ' /etc/apt/sources.list; then
	sed -i -E '/^deb .*/{/non-free-firmware/!s/$/ contrib non-free non-free-firmware/}' /etc/apt/sources.list
	_found_components=1
fi
if [[ "$_found_components" -eq 0 ]]; then
	echo "ERROR: found no /etc/apt/sources.list(.d) entry to add contrib/non-free/non-free-firmware to." >&2
	echo "       nvidia-driver ships in Debian's non-free component; without it enabled the" >&2
	echo "       install below cannot resolve any nvidia package at all." >&2
	exit 1
fi
echo "==> apt sources after enabling components:"
cat /etc/apt/sources.list.d/*.sources /etc/apt/sources.list 2>/dev/null || true

export DEBIAN_FRONTEND=noninteractive
apt-get update -y

# linux-headers-${KVER} matches the base layer's baked kernel version.
# On sid / rolling archives where the archive has moved past the cached base
# layer's kernel (e.g. base kernel 7.1.7 vs archive headers 7.1.8), installing
# linux-headers-generic pulls headers for a newer kernel that dkms builds for,
# leaving /usr/lib/modules/${KVER}/build missing. If the exact versioned package
# has been removed from the archive, fall back to linux-headers-generic.
HEADERS_PKG="linux-headers-${KVER}"
if ! apt-cache show "$HEADERS_PKG" >/dev/null 2>&1; then
	echo "==> ${HEADERS_PKG} not available in apt archive; falling back to linux-headers-generic"
	HEADERS_PKG="linux-headers-generic"
fi

# libnvidia-allocator1 is what ships nvidia-drm_gbm.so, the GBM backend every
# Wayland compositor loads to get a buffer out of the driver. Debian keeps it
# in its own binary package and nvidia-driver-libs only Recommends it, so
# --no-install-recommends left it out and every flounder *-nvidia image failed
# verify-nvidia-debian.sh on "missing nvidia-drm_gbm.so" while the rest of the
# driver stack was present and correct (tuna-os/tunaOS#1564). Naming it here
# rather than dropping --no-install-recommends keeps the package set explicit;
# the recommends set for this stack pulls in Xorg, which these images do not
# ship. libnvidia-egl-gbm1 is the EGL external-platform half of the same path
# and is a Recommends for the same reason.
apt-get install -y --no-install-recommends \
	dkms \
	"${HEADERS_PKG}" \
	nvidia-kernel-dkms \
	nvidia-driver-libs \
	nvidia-vulkan-icd \
	nvidia-settings \
	libnvidia-allocator1 \
	libnvidia-egl-gbm1 \
	libgl1-nvidia-glvnd-glx

if [[ ! -e "/usr/lib/modules/${KVER}/build" ]]; then
	echo "ERROR: /usr/lib/modules/${KVER}/build is missing after installing linux-headers-generic —" >&2
	echo "       dkms has no headers to build the nvidia module against for ${KVER}." >&2
	exit 1
fi

echo "==> dkms status before build:"
dkms status || true

# Explicit build+install rather than trusting apt/dkms triggers to fire
# correctly in a container build with no running system bus — same
# reasoning as the RPM and Arch overlays' explicit dracut/dkms runs instead
# of relying on package postinst scriptlets.
dkms autoinstall -k "${KVER}"

echo "==> dkms status after build:"
dkms status

# Prove the module actually landed for THIS kernel by finding the built
# file, not by string-matching dkms status output (whose module name and
# phrasing are not a stable contract — see header). A missing .ko here is a
# black screen on real hardware, so this is a hard failure.
# Debian's nvidia-kernel-dkms is alternatives-managed, so its DKMS module is
# named nvidia-current and the file it installs is nvidia-current.ko.xz --
# 'nvidia.ko*' never matches it. That is not a hypothetical: flounder's
# gnome/kde/xfce-nvidia images failed here on every nightly while the build
# above printed "Building module(s)... done.", signed five modules, installed
# nvidia-current.ko.xz, and reported "installed" in dkms status. The comment
# above is right that dkms status text is not a contract; the module FILENAME
# is not one either, so match the names this distro actually uses and keep
# NVIDIA_KO pointing at the core module (not -modeset/-drm/-uvm/-peermem) so
# the modinfo version check below still reads the right file.
NVIDIA_KO=""
for _nv_base in nvidia nvidia-current; do
	NVIDIA_KO="$(find "/usr/lib/modules/${KVER}" -name "${_nv_base}.ko*" -print -quit)"
	[[ -n "$NVIDIA_KO" ]] && break
done
unset _nv_base
if [[ -z "$NVIDIA_KO" ]]; then
	echo "ERROR: dkms did not produce nvidia.ko for ${KVER} — dkms status above shows why." >&2
	exit 1
fi
echo "==> built module: ${NVIDIA_KO}"
if command -v modinfo >/dev/null 2>&1; then
	modinfo "$NVIDIA_KO" | grep -E '^(version|vermagic):' || true
fi

# Written directly rather than relying on nvidia-kernel-support's
# alternatives-managed /etc/nvidia/current/nvidia-blacklists-nouveau.conf:
# that file's presence at /etc/modprobe.d is contingent on the alternatives
# symlink the package sets up, one more moving part this overlay does not
# need. Same approach as the RPM and Arch overlays.
tee /usr/lib/modprobe.d/00-nouveau-blacklist.conf <<'EOF'
blacklist nouveau
options nouveau modeset=0
EOF

install -d /usr/lib/bootc/kargs.d
tee /usr/lib/bootc/kargs.d/00-nvidia.toml <<'EOF'
kargs = ["rd.driver.blacklist=nouveau", "modprobe.blacklist=nouveau", "nvidia-drm.modeset=1"]
EOF

# Force the driver into the initramfs. Debian's nvidia packaging assumes
# initramfs-tools (update-initramfs), never dracut — every TunaOS bootc
# variant, flounder/flounder-sid included, builds its initramfs with dracut
# instead (Containerfile.debian's own dracut step), so this file has to be
# written directly rather than adjusted from a package-shipped one, same as
# the Arch overlay. i915/amdgpu are preloaded first so Chromium's hardware
# acceleration still finds an iGPU on hybrid-graphics laptops (same ordering
# as overrides/nvidia/20-nvidia.sh).
install -d /usr/lib/dracut/dracut.conf.d
tee /usr/lib/dracut/dracut.conf.d/99-nvidia.conf <<'EOF'
force_drivers+=" i915 amdgpu nvidia nvidia_modeset nvidia_uvm nvidia_drm "
EOF

# --tmpdir /boot: dracut defaults to /var/tmp, not guaranteed to exist
# outside the base image's own build (99-cleanup.sh's header documents the
# same landmine for the live-ISO rebuild path). /boot is always present in
# this stage. Positional path+kver invocation matches Containerfile.debian's
# own dracut call; compression and the bootc/composefs module set come from
# the persisted dracut.conf.d/30-bootc-container-build.conf the base image
# already wrote.
dracut --force --no-hostonly --reproducible --tmpdir /boot \
	"/usr/lib/modules/${KVER}/initramfs.img" "${KVER}"

apt-get clean -y
rm -rf /var/lib/apt/lists/*
