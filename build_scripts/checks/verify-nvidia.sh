#!/usr/bin/env bash
# verify-nvidia.sh — fatal build-time contract for *-nvidia overlay images.
#
# WHY THIS EXISTS. Every way an NVIDIA image fails on real hardware is
# statically visible in the image, and for months the statically visible
# truth was "there is no NVIDIA in the nvidia image": the overlay's
# run_buildscripts_for found no overrides directory, silently skipped, and
# published *-nvidia tags that were byte-for-byte their parent plus VS Code
# hooks. No check could contradict it because nothing asserted a single
# nvidia file. This script is the independent auditor of the install layer
# (build_scripts/overlay/overrides/nvidia/20-nvidia.sh): it re-derives every
# claim from the filesystem and the rpm database rather than trusting that
# the install script ran.
#
# Assertion sources — measured, not guessed (repo rule: never assert a glob
# you have not seen resolve). File paths below were read out of negativo17
# fedora-nvidia 43 repodata filelists (2026-08-07), the exact repo the
# install script points these images at:
#   /usr/share/glvnd/egl_vendor.d/10_nvidia.json      (nvidia-driver-libs)
#   /usr/share/vulkan/icd.d/nvidia_icd.*.json         (per-arch name)
#   /usr/lib64/gbm/nvidia-drm_gbm.so                  (Wayland GBM backend)
#   /usr/lib64/libEGL_nvidia.so.0, libGLX_nvidia.so.0
#   /usr/lib/dracut/dracut.conf.d/99-nvidia.conf      (nvidia-kmod-common)
# That packaging ships NO nvidia-suspend/resume/hibernate units (it ships
# persistenced + powerd), so the suspend check is conditional: present units
# must be enabled; absent units are reported, not failed.
#
# Scope: the dnf/rpm family only — the only family that declares -nvidia
# flavors in .github/build-config.yml (yellowfin/albacore/skipjack on the
# centos-10 akmods, bonito/bonito-rawhide on coreos-stable). If a non-rpm
# variant ever grows an nvidia flavor this exits loudly rather than
# pretending to have verified something it cannot.
#
# Test hooks (same pattern as TUNAOS_OS_RELEASE in verify-branding.sh):
#   TUNAOS_NVIDIA_VERIFY_ROOT  prefix for every filesystem path, so bats can
#                              run the real logic against a fixture tree.
#   rpm/modinfo/systemctl are resolved via PATH, so tests stub them.

set -euo pipefail

NV_ROOT="${TUNAOS_NVIDIA_VERIFY_ROOT:-}"

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

if ! command -v rpm >/dev/null 2>&1; then
	echo "ERROR: verify-nvidia.sh only knows the rpm family, and this image has no rpm." >&2
	echo "       No non-rpm variant declares an nvidia flavor; if one now does," >&2
	echo "       teach this contract that family first." >&2
	exit 1
fi

echo "== packages =="
for pkg in kmod-nvidia nvidia-driver nvidia-driver-cuda nvidia-container-toolkit; do
	if v=$(rpm -q --queryformat '%{VERSION}' "$pkg" 2>/dev/null); then
		pass "${pkg}=${v}"
	else
		fail "${pkg} is not installed"
	fi
done

echo "== kernel/module coherence =="
# The kmod must exist for the EXACT kernel this image ships — a kmod for any
# other kernel is a black screen on real hardware while every package
# transaction "succeeded".
KERNEL_VRA="$(rpm -q kernel --queryformat '%{EVR}.%{ARCH}\n' 2>/dev/null | tail -1 || true)"
MODULE_FILE=""
if [[ -z "$KERNEL_VRA" ]]; then
	fail "cannot determine kernel EVR (rpm -q kernel failed)"
elif [[ ! -d "${NV_ROOT}/usr/lib/modules/${KERNEL_VRA}" ]]; then
	fail "no module directory for the shipped kernel: /usr/lib/modules/${KERNEL_VRA}"
else
	# Ask rpm which module files the kmod package OWNS — never glob by name.
	# The first proof build (run 31196251408) failed on exactly that: the
	# nvidia*.ko* glob matched nvidia-wmi-ec-backlight.ko.xz, a mainline
	# module every kernel ships, and modinfo rightly found no driver version
	# in it. A name glob also passes on an image with no kmod at all, which
	# inverts the check's whole purpose.
	# UsrMove: the kmod RPM RECORDS its payload under /lib/modules — measured
	# from the actual akmods bundle (rpm -qlp on
	# kmod-nvidia-6.12.0-254.el10.x86_64-610.43.03-1.el10.x86_64.rpm prints
	# ./lib/modules/<kver>/extra/nvidia/nvidia*.ko.xz) — while the files
	# resolve on disk through the /lib -> /usr/lib symlink. Demanding the
	# /usr-prefixed form in the rpm -ql output is how proof build #3 (run
	# 31202648166) failed with a fully installed, version-locked driver.
	# Match the kernel-dir substring either way, then resolve the on-disk
	# location with a /usr fallback for roots without the symlink.
	MODULE_FILE="$(rpm -ql kmod-nvidia 2>/dev/null |
		grep -E '\.ko(\.[a-z0-9]+)?$' |
		grep -F "lib/modules/${KERNEL_VRA}/" |
		head -1 || true)"
	if [[ -n "$MODULE_FILE" && ! -e "${NV_ROOT}${MODULE_FILE}" && -e "${NV_ROOT}/usr${MODULE_FILE}" ]]; then
		MODULE_FILE="/usr${MODULE_FILE}"
	fi
	if [[ -n "$MODULE_FILE" && -e "${NV_ROOT}${MODULE_FILE}" ]]; then
		MODULE_FILE="${NV_ROOT}${MODULE_FILE}"
		pass "kmod-nvidia ships a module for ${KERNEL_VRA} (${MODULE_FILE#"${NV_ROOT}"})"
	elif [[ -n "$MODULE_FILE" ]]; then
		MODULE_FILE=""
		fail "kmod-nvidia's module list names files absent on disk under lib/modules/${KERNEL_VRA}"
	else
		# Evidence with the failure: what rpm actually owns, so the next
		# mismatch names itself instead of costing a diagnosis round.
		rpm -ql kmod-nvidia 2>/dev/null | head -10 | sed 's/^/    rpm -ql: /' || true
		MODULE_FILE=""
		fail "kmod-nvidia owns no .ko under lib/modules/${KERNEL_VRA} — kmod built for a different kernel?"
	fi
fi

echo "== version lock (kmod == userspace) =="
KMOD_VERSION="$(rpm -q --queryformat '%{VERSION}' kmod-nvidia 2>/dev/null || true)"
DRIVER_VERSION="$(rpm -q --queryformat '%{VERSION}' nvidia-driver 2>/dev/null || true)"
if [[ -n "$KMOD_VERSION" && -n "$DRIVER_VERSION" ]]; then
	if [[ "$KMOD_VERSION" == "$DRIVER_VERSION" ]]; then
		pass "kmod-nvidia and nvidia-driver agree (${KMOD_VERSION})"
	else
		fail "version skew: kmod-nvidia=${KMOD_VERSION} but nvidia-driver=${DRIVER_VERSION}"
	fi
fi
# File-level proof the .ko really is that version (catches a stale module
# left behind by a partial overlay rebuild, which rpm -q cannot see).
if [[ -n "$MODULE_FILE" && -n "$KMOD_VERSION" ]] && command -v modinfo >/dev/null 2>&1; then
	MODINFO_VERSION="$(modinfo -F version "$MODULE_FILE" 2>/dev/null | head -1 || true)"
	if [[ -z "$MODINFO_VERSION" ]]; then
		fail "modinfo could not read a version from ${MODULE_FILE#"${NV_ROOT}"}"
	elif [[ "$MODINFO_VERSION" == "$KMOD_VERSION" ]]; then
		pass "module file version matches kmod rpm (${MODINFO_VERSION})"
	else
		fail "module file is ${MODINFO_VERSION} but kmod-nvidia rpm is ${KMOD_VERSION}"
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
# Each pair is (dispatch JSON, the library it names). A JSON without its
# library renders as "no NVIDIA GPU found" in every GL/Vulkan app.
if compgen -G "${NV_ROOT}/usr/share/glvnd/egl_vendor.d/10_nvidia.json" >/dev/null; then
	pass "glvnd EGL vendor JSON present"
else
	fail "missing /usr/share/glvnd/egl_vendor.d/10_nvidia.json"
fi
if compgen -G "${NV_ROOT}/usr/lib64/libEGL_nvidia.so.0" >/dev/null; then
	pass "libEGL_nvidia.so.0 present"
else
	fail "missing /usr/lib64/libEGL_nvidia.so.0"
fi
if compgen -G "${NV_ROOT}/usr/share/vulkan/icd.d/nvidia_icd.*.json" >/dev/null; then
	pass "Vulkan ICD JSON present"
else
	fail "missing /usr/share/vulkan/icd.d/nvidia_icd.*.json"
fi
if compgen -G "${NV_ROOT}/usr/lib64/libGLX_nvidia.so.0" >/dev/null; then
	pass "libGLX_nvidia.so.0 present"
else
	fail "missing /usr/lib64/libGLX_nvidia.so.0"
fi
if compgen -G "${NV_ROOT}/usr/lib64/gbm/nvidia-drm_gbm.so" >/dev/null; then
	pass "GBM backend nvidia-drm_gbm.so present"
else
	fail "missing /usr/lib64/gbm/nvidia-drm_gbm.so — Wayland compositors cannot use the driver"
fi

echo "== initramfs policy =="
DRACUT_CONF="${NV_ROOT}/usr/lib/dracut/dracut.conf.d/99-nvidia.conf"
if [[ ! -f "$DRACUT_CONF" ]]; then
	fail "missing /usr/lib/dracut/dracut.conf.d/99-nvidia.conf (nvidia-kmod-common)"
elif grep -q 'force_drivers' "$DRACUT_CONF"; then
	pass "dracut force_drivers set for nvidia"
else
	fail "99-nvidia.conf does not force_drivers — black screen at boot on nvidia desktops"
fi

echo "== exactly one kernel tree =="
# The kernel swap must leave exactly ONE kernel module tree. rpm --erase
# keeps a directory alive when it holds generated (unowned) files, and a
# stale half-alive tree is a landmine for every consumer that scans
# /usr/lib/modules: the yellowfin:kde-nvidia live ISO resolved its kernel
# version against the leftover 6.12.0-250 husk (no vmlinuz, no initramfs,
# empty modules.dep), generated an initrd with tacklebox hooks and zero
# drivers, and hung in dracut with no sr0 ever appearing (run 31208526159)
# — while the swapped kernel's own initramfs, one directory over, carried
# every driver the boot needed.
#
# WHAT COUNTS AS A KERNEL TREE. Not every /usr/lib/modules entry is one, and
# counting them all is how this check failed six correct images (#1118, run
# 31235806989: "6 kernel module trees ... expected exactly
# 6.12.0-254.el10.x86_64", while every other assertion in the same log
# passed — kmod built for 6.12.0-254, module version matched, initramfs
# carried all eight boot drivers). Measured cause: the driver transaction
# pulls kernel-abi-stablelists from baseos, whose entire payload under
# /lib/modules is
#     kabi-current -> kabi-rhel103   (symlink to a directory)
#     kabi-rhel100 kabi-rhel101 kabi-rhel102 kabi-rhel103
# (rpm header of kernel-abi-stablelists-6.12.0-254.el10.noarch — 5 entries,
# holding kabi_stablelist_<arch> text files only). One real tree plus those
# five is the 6. A kabi directory has no vmlinuz, no modules.dep and no
# kernel-release name, so nothing that resolves a kernel version out of
# /usr/lib/modules can select one — they are reported, never counted.
#
# A kernel module tree is an entry named for a kernel release (uname -r,
# always <maj>.<min>.<patch>…) — which is exactly the shape of the husk this
# check exists to catch (6.12.0-250.el10.x86_64), so the failure mode is
# still fatal here.
_kernel_trees=()
_other_entries=()
for _tree in "${NV_ROOT}"/usr/lib/modules/*/; do
	[[ -d "$_tree" ]] || continue
	_tree_name="$(basename "$_tree")"
	if [[ "$_tree_name" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
		_kernel_trees+=("$_tree_name")
	else
		_other_entries+=("$_tree_name")
	fi
done
# Evidence with the verdict: name the entries, so the next mismatch does not
# cost a diagnosis round the way #1118 did (its log printed only the count).
if [[ "${#_other_entries[@]}" -gt 0 ]]; then
	echo "  info: non-kernel /usr/lib/modules entries (not kernel trees): ${_other_entries[*]}"
fi
if [[ "${#_kernel_trees[@]}" -ne 1 ]]; then
	fail "${#_kernel_trees[@]} kernel module trees under /usr/lib/modules (${_kernel_trees[*]:-none}) — a stale tree breaks kernel/initrd selection downstream (expected exactly ${KERNEL_VRA})"
elif [[ "${_kernel_trees[0]}" == "$KERNEL_VRA" ]]; then
	pass "single kernel module tree (${_kernel_trees[0]})"
else
	fail "single module tree ${_kernel_trees[0]} does not match the installed kernel ${KERNEL_VRA}"
fi

echo "== initramfs boot-driver parity =="
# The rebuilt initramfs must serve BOTH boots: the live ISO (virtio-scsi CD:
# virtio_scsi + sr_mod + cdrom + isofs, squashfs/overlay/loop for the live
# root) and the installed disk (virtio_blk). Names measured with lsinitrd on
# the PASSING parent image (yellowfin:kde, 705 modules) and confirmed
# present in the nvidia image's swapped-kernel initramfs (720 modules) —
# this is a parity floor, not a wish list; dm_crypt is deliberately absent
# because the parent's initramfs does not carry it either.
#
# A driver satisfies the floor two ways, and the check must accept BOTH: as a
# .ko in the initramfs, or built into the kernel image. Requiring only the
# first made the floor a property of the kernel's build config rather than of
# the boot path, and that broke the moment the kernel changed (#1561). The
# floor was measured on EL10, where the CentOS Stream 10 config has
# CONFIG_BLK_DEV_SR=m and CONFIG_VIRTIO_BLK=m. Fedora 43 sets both to =y, so
# on fc43 sr_mod, cdrom (selected by BLK_DEV_SR) and virtio_blk are vmlinuz
# builtins with no .ko for dracut to install or lsinitrd to list — and every
# bonito/bonito-rawhide nvidia flavor plus gnome-nvidia-hwe on three EL
# variants failed on drivers that were present all along. gnome-hwe on the
# same kernel passed the full qcow2 boot gate in those same runs, which is
# what a virtio_blk boot working looks like.
#
# modules.builtin is the kernel's own record of that, shipped per-kernel-tree,
# so this stays a measurement rather than a hardcoded fc43 exemption: a driver
# that is neither in the initramfs nor builtin is still a real failure.
INITRAMFS="${NV_ROOT}/usr/lib/modules/${KERNEL_VRA}/initramfs.img"
BUILTIN="${NV_ROOT}/usr/lib/modules/${KERNEL_VRA}/modules.builtin"
_builtin_list=""
if [[ -s "$BUILTIN" ]]; then
	_builtin_list="$(<"$BUILTIN")"
fi
if [[ ! -s "$INITRAMFS" ]]; then
	fail "missing or empty initramfs for the installed kernel: /usr/lib/modules/${KERNEL_VRA}/initramfs.img"
elif ! command -v lsinitrd >/dev/null 2>&1; then
	fail "lsinitrd is unavailable — cannot prove the initramfs carries the boot drivers"
else
	_initrd_list="$(lsinitrd "$INITRAMFS" 2>/dev/null || true)"
	for _drv in sr_mod cdrom isofs squashfs virtio_scsi virtio_blk overlay loop; do
		# modules.builtin records bare relative paths (kernel/drivers/scsi/
		# sr_mod.ko), never a compression suffix — anchor the end so cdrom
		# cannot be satisfied by some other module that merely contains it.
		if grep -qE "/${_drv}\.ko" <<<"$_initrd_list"; then
			pass "initramfs carries ${_drv}"
		elif [[ -n "$_builtin_list" ]] && grep -qE "(^|/)${_drv}\.ko$" <<<"$_builtin_list"; then
			pass "${_drv} is built into the kernel (modules.builtin) — no .ko to carry"
		elif [[ ! -s "$BUILTIN" ]]; then
			fail "initramfs is missing ${_drv}, and /usr/lib/modules/${KERNEL_VRA}/modules.builtin is missing or empty so it cannot be shown to be builtin either — the live ISO or installed boot cannot mount its root"
		else
			fail "initramfs is missing ${_drv} and it is not built into the kernel — the live ISO or installed boot cannot mount its root"
		fi
	done
fi

echo "== suspend units (conditional — see header) =="
for unit in nvidia-suspend nvidia-resume nvidia-hibernate; do
	if [[ -f "${NV_ROOT}/usr/lib/systemd/system/${unit}.service" ]]; then
		if systemctl is-enabled "${unit}.service" >/dev/null 2>&1; then
			pass "${unit}.service shipped and enabled"
		else
			fail "${unit}.service is shipped but not enabled"
		fi
	else
		echo "  info: ${unit}.service not shipped by this driver packaging (expected on negativo17)"
	fi
done

echo
if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_NVIDIA_CONTRACT_FAIL failures=${fails}"
	exit 1
fi
echo "TUNAOS_NVIDIA_CONTRACT_OK"
