#!/usr/bin/env bash
# verify-nvidia-debian.sh — fatal build-time contract for flounder /
# flounder-sid (Debian) *-nvidia overlay images. Sibling of verify-nvidia.sh
# (dnf/rpm) and verify-nvidia-arch.sh (pacman) — see verify-nvidia.sh's
# header for why this class of check exists at all (tunaOS was shipping
# driverless "nvidia" images for months because nothing asserted a single
# nvidia file).
#
# Assertion sources — measured, not guessed:
#   /usr/lib/x86_64-linux-gnu/nvidia/current/libEGL_nvidia.so.0,
#   libGLX_nvidia.so.0, nvidia-drm_gbm.so,
#   /usr/share/glvnd/egl_vendor.d/10_nvidia.json,
#   /usr/share/vulkan/icd.d/nvidia_icd.json
# read out of the trixie non-free Contents-amd64 index
# (ftp.debian.org/debian/dists/trixie/non-free/Contents-amd64.gz,
# 2026-08-08) for nvidia-driver 550.163.01. Debian's driver libraries live
# under the "current" alternatives-managed symlink at
# /usr/lib/x86_64-linux-gnu/nvidia/current/ — a multiarch-triplet path,
# unlike Arch's flat /usr/lib and RPM's /usr/lib64. The Vulkan ICD JSON is
# a single fixed filename here (nvidia_icd.json), not the per-arch-suffixed
# glob (nvidia_icd.*.json) the RPM contract uses.
#
# The dkms-built module's exact registered name is NOT asserted (see
# overrides/nvidia-debian/20-nvidia.sh's header on why) — this script finds
# the built .ko by glob under the kernel's module tree instead, matching
# how the install script itself proves success.
#
# Test hooks (same pattern as TUNAOS_NVIDIA_VERIFY_ROOT in verify-nvidia.sh):
#   TUNAOS_NVIDIA_VERIFY_ROOT  prefix for every filesystem path, so bats can
#                              run the real logic against a fixture tree.
#   dpkg/modinfo/dracut are resolved via PATH, so tests stub them.

set -euo pipefail

NV_ROOT="${TUNAOS_NVIDIA_VERIFY_ROOT:-}"

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

if ! command -v dpkg >/dev/null 2>&1; then
	echo "ERROR: verify-nvidia-debian.sh only knows the dpkg family, and this image has" >&2
	echo "       no dpkg. This check is dispatched from nvidia.sh based on IS_DEBIAN; if" >&2
	echo "       that dispatch is wrong, fix nvidia.sh rather than this script." >&2
	exit 1
fi

echo "== packages =="
for pkg in nvidia-kernel-dkms nvidia-driver-libs nvidia-vulkan-icd nvidia-settings dkms; do
	if v=$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null); then
		pass "${pkg}=${v}"
	else
		fail "${pkg} is not installed"
	fi
done

echo "== kernel/module coherence =="
# The dkms-built module must exist for the kernel this image actually ships.
# Found by glob rather than asserting a registered dkms module name — see
# header — the same reasoning that made verify-nvidia.sh stop name-globbing
# on the RPM side (the wmi-ec-backlight false match, run 31196251408).
KERNEL_TREES=()
for _tree in "${NV_ROOT}"/usr/lib/modules/*/; do
	[[ -d "$_tree" ]] || continue
	_name="$(basename "$_tree")"
	[[ "$_name" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]] && KERNEL_TREES+=("$_name")
done
if [[ "${#KERNEL_TREES[@]}" -ne 1 ]]; then
	fail "${#KERNEL_TREES[@]} kernel module trees under /usr/lib/modules (${KERNEL_TREES[*]:-none}) — expected exactly 1"
	KVER=""
else
	KVER="${KERNEL_TREES[0]}"
	pass "single kernel module tree (${KVER})"
fi

MODULE_FILE=""
if [[ -n "$KVER" ]]; then
	# nvidia-current.ko.xz, not nvidia.ko: Debian's nvidia-kernel-dkms is
	# alternatives-managed and its DKMS module is named nvidia-current. The
	# core module only, so the modinfo version check below does not end up
	# reading -modeset/-drm/-uvm/-peermem instead.
	for _nv_base in nvidia nvidia-current; do
		MODULE_FILE="$(find "${NV_ROOT}/usr/lib/modules/${KVER}" -name "${_nv_base}.ko*" -print -quit 2>/dev/null || true)"
		[[ -n "$MODULE_FILE" ]] && break
	done
	unset _nv_base
	if [[ -n "$MODULE_FILE" ]]; then
		pass "dkms built a module for ${KVER} (${MODULE_FILE#"${NV_ROOT}"})"
	else
		fail "no nvidia.ko under /usr/lib/modules/${KVER} — dkms did not build for this kernel"
	fi
fi

if [[ -n "$MODULE_FILE" ]] && command -v modinfo >/dev/null 2>&1; then
	MODINFO_VERSION="$(modinfo -F version "$MODULE_FILE" 2>/dev/null | head -1 || true)"
	DRIVER_VERSION="$(dpkg-query -W -f='${Version}' nvidia-driver-libs 2>/dev/null || true)"
	if [[ -z "$MODINFO_VERSION" ]]; then
		fail "modinfo could not read a version from ${MODULE_FILE#"${NV_ROOT}"}"
	elif [[ -n "$DRIVER_VERSION" && "$MODINFO_VERSION" != "${DRIVER_VERSION%%-*}" ]]; then
		fail "kmod version (${MODINFO_VERSION}) does not match nvidia-driver-libs (${DRIVER_VERSION})"
	else
		pass "module version matches nvidia-driver-libs (${MODINFO_VERSION})"
	fi
fi

echo "== nouveau is out of the way =="
if grep -rqs 'blacklist nouveau' "${NV_ROOT}/usr/lib/modprobe.d" "${NV_ROOT}/etc/modprobe.d" 2>/dev/null; then
	pass "nouveau blacklisted in modprobe.d"
else
	fail "no 'blacklist nouveau' under /usr/lib/modprobe.d or /etc/modprobe.d"
fi
if grep -rqs 'nvidia-drm.modeset=1' "${NV_ROOT}/usr/lib/bootc/kargs.d" 2>/dev/null; then
	pass "nvidia-drm.modeset=1 karg declared in /usr/lib/bootc/kargs.d"
else
	fail "nvidia-drm.modeset=1 missing from /usr/lib/bootc/kargs.d — Wayland/KMS will not engage"
fi

echo "== GL/Vulkan/Wayland plumbing =="
# Debian's driver libraries live under the alternatives-managed "current"
# symlink at this multiarch-triplet path — not RPM's /usr/lib64, not
# Arch's flat /usr/lib.
NVLIB="${NV_ROOT}/usr/lib/x86_64-linux-gnu/nvidia/current"
if compgen -G "${NV_ROOT}/usr/share/glvnd/egl_vendor.d/10_nvidia.json" >/dev/null; then
	pass "glvnd EGL vendor JSON present"
else
	fail "missing /usr/share/glvnd/egl_vendor.d/10_nvidia.json"
fi
if compgen -G "${NVLIB}/libEGL_nvidia.so.0" >/dev/null; then
	pass "libEGL_nvidia.so.0 present"
else
	fail "missing /usr/lib/x86_64-linux-gnu/nvidia/current/libEGL_nvidia.so.0"
fi
if compgen -G "${NV_ROOT}/usr/share/vulkan/icd.d/nvidia_icd.json" >/dev/null; then
	pass "Vulkan ICD JSON present"
else
	fail "missing /usr/share/vulkan/icd.d/nvidia_icd.json"
fi
if compgen -G "${NVLIB}/libGLX_nvidia.so.0" >/dev/null; then
	pass "libGLX_nvidia.so.0 present"
else
	fail "missing /usr/lib/x86_64-linux-gnu/nvidia/current/libGLX_nvidia.so.0"
fi
if compgen -G "${NVLIB}/nvidia-drm_gbm.so" >/dev/null; then
	pass "GBM backend nvidia-drm_gbm.so present"
else
	fail "missing /usr/lib/x86_64-linux-gnu/nvidia/current/nvidia-drm_gbm.so — Wayland compositors cannot use the driver"
fi
# The backend above is loaded THROUGH the EGL external-platform registration,
# not directly: without 15_nvidia_gbm.json, EGL never looks for the GBM
# platform and nvidia-drm_gbm.so sits on disk doing nothing. Checking only the
# .so made "Wayland compositors can use the driver" provable in a state where
# they still could not — and, unlike the .so, nothing in the nvidia-driver
# dependency chain pulls this in even with Recommends enabled, so it can only
# ever arrive by being named in the install list (tunaOS#1564). Path read from
# libnvidia-egl-gbm1's file list (trixie 1.1.2.1-1; same version in unstable).
if compgen -G "${NV_ROOT}/usr/share/egl/egl_external_platform.d/15_nvidia_gbm.json" >/dev/null; then
	pass "EGL GBM external platform registered"
else
	fail "missing /usr/share/egl/egl_external_platform.d/15_nvidia_gbm.json (libnvidia-egl-gbm1) — EGL will not load the GBM backend"
fi

echo "== initramfs policy =="
DRACUT_CONF="${NV_ROOT}/usr/lib/dracut/dracut.conf.d/99-nvidia.conf"
if [[ ! -f "$DRACUT_CONF" ]]; then
	fail "missing /usr/lib/dracut/dracut.conf.d/99-nvidia.conf"
elif grep -q 'force_drivers' "$DRACUT_CONF"; then
	pass "dracut force_drivers set for nvidia"
else
	fail "99-nvidia.conf does not force_drivers — black screen at boot on nvidia desktops"
fi

echo "== initramfs present for the shipped kernel =="
if [[ -n "$KVER" ]]; then
	INITRAMFS="${NV_ROOT}/usr/lib/modules/${KVER}/initramfs.img"
	if [[ -s "$INITRAMFS" ]]; then
		pass "initramfs present for ${KVER}"
	else
		fail "missing or empty initramfs for the installed kernel: /usr/lib/modules/${KVER}/initramfs.img"
	fi
fi

echo
if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_NVIDIA_DEBIAN_CONTRACT_FAIL failures=${fails}"
	exit 1
fi
echo "TUNAOS_NVIDIA_DEBIAN_CONTRACT_OK"
