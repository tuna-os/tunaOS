#!/usr/bin/env bash
# verify-nvidia-arch.sh — fatal build-time contract for marlin (Arch)
# *-nvidia overlay images. Sibling of verify-nvidia.sh (the dnf/rpm family
# contract) — see that file's header for why this class of check exists at
# all (tunaOS was shipping driverless "nvidia" images for months because
# nothing asserted a single nvidia file). Kept as a separate script rather
# than teaching verify-nvidia.sh a second package family: that script's own
# header commits to exiting loudly rather than pretending to verify a
# family it does not know, and the two families' assertions (rpm -q vs
# pacman -Q, dracut 99-nvidia.conf contents, module search paths) share no
# code worth factoring — see nvidia.sh for the dispatch between them.
#
# Assertion sources — measured, not guessed:
#   /usr/lib/libEGL_nvidia.so.0, libGLX_nvidia.so.0,
#   /usr/lib/gbm/nvidia-drm_gbm.so,
#   /usr/share/glvnd/egl_vendor.d/10_nvidia.json,
#   /usr/share/vulkan/icd.d/nvidia_icd.json
# read out of the Arch package file list for nvidia-utils 610.57.04-1
# (archlinux.org/packages/extra/x86_64/nvidia-utils/files/, 2026-08-08).
# Arch's /usr/lib has no lib64 or multiarch-triplet split (single x86_64
# tree), unlike the RPM (/usr/lib64) and Debian
# (/usr/lib/x86_64-linux-gnu) families — do not port those paths here.
#
# The dkms-built module's exact registered name is NOT asserted (see
# overrides/nvidia-arch/20-nvidia.sh's header on why) — this script finds
# the built .ko by glob under the kernel's module tree instead, matching
# how the install script itself proves success.
#
# Test hooks (same pattern as TUNAOS_NVIDIA_VERIFY_ROOT in verify-nvidia.sh):
#   TUNAOS_NVIDIA_VERIFY_ROOT  prefix for every filesystem path, so bats can
#                              run the real logic against a fixture tree.
#   pacman/modinfo/dracut are resolved via PATH, so tests stub them.

set -euo pipefail

NV_ROOT="${TUNAOS_NVIDIA_VERIFY_ROOT:-}"

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

if ! command -v pacman >/dev/null 2>&1; then
	echo "ERROR: verify-nvidia-arch.sh only knows the pacman family, and this image has" >&2
	echo "       no pacman. This check is dispatched from nvidia.sh based on IS_ARCH; if" >&2
	echo "       that dispatch is wrong, fix nvidia.sh rather than this script." >&2
	exit 1
fi

echo "== packages =="
for pkg in nvidia-open-dkms nvidia-utils nvidia-settings dkms egl-wayland; do
	if v=$(pacman -Q --info "$pkg" 2>/dev/null | awk -F': ' '/^Version/{print $2; exit}'); then
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
	MODULE_FILE="$(find "${NV_ROOT}/usr/lib/modules/${KVER}" -name 'nvidia.ko*' -print -quit 2>/dev/null || true)"
	if [[ -n "$MODULE_FILE" ]]; then
		pass "dkms built a module for ${KVER} (${MODULE_FILE#"${NV_ROOT}"})"
	else
		fail "no nvidia.ko under /usr/lib/modules/${KVER} — dkms did not build for this kernel"
	fi
fi

if [[ -n "$MODULE_FILE" ]] && command -v modinfo >/dev/null 2>&1; then
	MODINFO_VERSION="$(modinfo -F version "$MODULE_FILE" 2>/dev/null | head -1 || true)"
	NVUTILS_VERSION="$(pacman -Q --info nvidia-utils 2>/dev/null | awk -F': ' '/^Version/{print $2; exit}' | cut -d- -f1 || true)"
	if [[ -z "$MODINFO_VERSION" ]]; then
		fail "modinfo could not read a version from ${MODULE_FILE#"${NV_ROOT}"}"
	elif [[ -n "$NVUTILS_VERSION" && "$MODINFO_VERSION" != "$NVUTILS_VERSION" ]]; then
		fail "kmod version (${MODINFO_VERSION}) does not match nvidia-utils (${NVUTILS_VERSION})"
	else
		pass "module version matches nvidia-utils (${MODINFO_VERSION})"
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
# Arch's /usr/lib is a single unified tree — no lib64, no multiarch triplet.
if compgen -G "${NV_ROOT}/usr/share/glvnd/egl_vendor.d/10_nvidia.json" >/dev/null; then
	pass "glvnd EGL vendor JSON present"
else
	fail "missing /usr/share/glvnd/egl_vendor.d/10_nvidia.json"
fi
if compgen -G "${NV_ROOT}/usr/lib/libEGL_nvidia.so.0" >/dev/null; then
	pass "libEGL_nvidia.so.0 present"
else
	fail "missing /usr/lib/libEGL_nvidia.so.0"
fi
if compgen -G "${NV_ROOT}/usr/share/vulkan/icd.d/nvidia_icd.json" >/dev/null; then
	pass "Vulkan ICD JSON present"
else
	fail "missing /usr/share/vulkan/icd.d/nvidia_icd.json"
fi
if compgen -G "${NV_ROOT}/usr/lib/libGLX_nvidia.so.0" >/dev/null; then
	pass "libGLX_nvidia.so.0 present"
else
	fail "missing /usr/lib/libGLX_nvidia.so.0"
fi
if compgen -G "${NV_ROOT}/usr/lib/gbm/nvidia-drm_gbm.so" >/dev/null; then
	pass "GBM backend nvidia-drm_gbm.so present"
else
	fail "missing /usr/lib/gbm/nvidia-drm_gbm.so — Wayland compositors cannot use the driver"
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
	echo "TUNAOS_NVIDIA_ARCH_CONTRACT_FAIL failures=${fails}"
	exit 1
fi
echo "TUNAOS_NVIDIA_ARCH_CONTRACT_OK"
