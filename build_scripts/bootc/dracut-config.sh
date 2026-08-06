#!/usr/bin/env bash
# dracut-config.sh — write the dracut configuration a bootc image needs.
#
# WHY THIS EXISTS
#
# Every bootc variant needs the same three things from dracut, and until this
# script each Containerfile spelled them out itself, in its own order, with its
# own omissions:
#
#   Containerfile.arch      add_dracutmodules " bootc crypt dm ", omit tpm2-tss pcsc, add_drivers erofs
#   Containerfile.debian    add_dracutmodules " bootc "
#   Containerfile.opensuse  add_dracutmodules " bootc crypt dm ", omit tpm2-tss pcsc, install_items
#   Containerfile.gentoo    (none)
#   Containerfile.ubuntu    omit pcsc
#
# Those differences are not deliberate distro tuning. They are the order the
# variants happened to be debugged in, and each one is a place a later fix has
# to be re-typed or silently forgotten.
#
# It was: five of six variants enable composefs, and only Arch carried the
# erofs driver — because that fix was made while chasing marlin and had nowhere
# shared to live. A composefs root IS an EROFS image with an overlayfs on top,
# so "this image is composefs" and "its initramfs can mount erofs" are the same
# fact stated twice, and they had drifted apart on four variants.
#
# So composefs is detected from the image itself (prepare-root.conf, the same
# thing scripts/lib/common.sh probes to choose the install path) rather than
# passed in, and the drivers follow from it. A variant cannot enable composefs
# and forget the driver any more.
#
# DRIVERS ARE PROBED, NOT ASSERTED
#
# add_drivers on a name the kernel does not have as a module is not free:
# dracut-install treats it as an error, so listing erofs unconditionally would
# break any base that builds it in (=y) or omits it. Each candidate is checked
# against the running kernel's module set first, and built-ins are skipped
# because they need no inclusion. That is why this is a script and not a
# printf.
#
# USAGE
#   dracut-config.sh [kver]
#
# kver defaults to the newest directory under /usr/lib/modules. Nothing here
# runs dracut — the Containerfiles do that themselves, because the invocation
# differs (Debian passes KVER positionally, Arch passes an output path).

set -euo pipefail
printf "::group:: === bootc dracut config ===\n"

# Prefix for every path this script reads or writes. Empty in a build; the
# tests point it at a fixture tree. Same idea as TUNAOS_OS_RELEASE in
# verify-branding.sh and TUNAOS_BUILD_CONFIG in get-base-image.sh — a script
# that can only be exercised inside a container build is a script whose bugs
# are found by a 40-minute matrix cell.
R="${TUNAOS_SYSROOT:-}"

CONF_DIR="${R}/usr/lib/dracut/dracut.conf.d"
mkdir -p "$CONF_DIR"

KVER="${1:-}"
if [[ -z "$KVER" ]]; then
	KVER="$(basename "$(find "${R}/usr/lib/modules" -maxdepth 1 -mindepth 1 -type d ! -name '*.img' 2>/dev/null | sort | tail -1)")"
fi
echo "kernel: ${KVER:-<none found>}"

# ── 1. systemd paths ─────────────────────────────────────────────────────────
# 51bootc's install() places its wants-symlink under ${systemdsystemconfdir}.
# openSUSE's dracut leaves that EMPTY, so the link lands at the initramfs root
# (/initrd-root-fs.target.wants/) where systemd never scans: the unit ships in
# the initramfs and is never pulled in, nothing consumes the composefs= karg,
# and switch-root finds no prepared root. Setting both paths explicitly is what
# makes 51bootc land correctly, and it is needed on every base, not just the
# one where it was first diagnosed.
printf 'systemdsystemconfdir=/etc/systemd/system\nsystemdsystemunitdir=/usr/lib/systemd/system\n' \
	>"${CONF_DIR}/30-fix-bootc-module.conf"

# ── 2. composefs detection ───────────────────────────────────────────────────
# Same signal scripts/lib/common.sh uses to decide how to INSTALL the image, so
# the initramfs and the installer cannot disagree about what the image is.
COMPOSEFS=0
if grep -A8 '^\[composefs\]' "${R}/usr/lib/ostree/prepare-root.conf" 2>/dev/null |
	grep -qiE 'enabled[[:space:]]*=[[:space:]]*(yes|true|1|signed)'; then
	COMPOSEFS=1
fi
echo "composefs: ${COMPOSEFS}"

# ── 3. drivers ───────────────────────────────────────────────────────────────
# A driver is worth adding only if it exists AS A MODULE for this kernel.
# Built-in (=y) needs no inclusion, and absent means add_drivers would fail the
# dracut run outright.
driver_is_module() {
	local drv="$1"
	[[ -n "$KVER" ]] || return 1
	# Fixture trees have no real module set, and modinfo would answer for the
	# HOST kernel — so the file check comes first whenever a prefix is set.
	if [[ -z "$R" ]] && command -v modinfo >/dev/null 2>&1; then
		modinfo -k "$KVER" "$drv" >/dev/null 2>&1 && return 0
		return 1
	fi
	find "${R}/usr/lib/modules/${KVER}" -name "${drv}.ko*" -print -quit 2>/dev/null | grep -q .
}

DRIVERS=()
if [[ "$COMPOSEFS" == 1 ]]; then
	# erofs: the composefs image itself. overlay: the writable layer over it.
	for drv in erofs overlay; do
		if driver_is_module "$drv"; then
			DRIVERS+=("$drv")
		else
			echo "note: ${drv} is not a module for ${KVER} (built in, or absent) — not adding"
		fi
	done
fi
# The root filesystem the installer formats. fisherman uses xfs today; ext4 and
# btrfs are listed because an image that cannot mount its own root filesystem
# fails identically and the cost of carrying them is a few hundred KB.
for drv in xfs ext4 btrfs; do
	driver_is_module "$drv" && DRIVERS+=("$drv")
done

# ── 4. modules ───────────────────────────────────────────────────────────────
# crypt/dm are named explicitly rather than left to autodetection: openSUSE's
# dracut defaults to hostonly, so a rebuild on a machine that is not itself
# LUKS-rooted quietly drops exactly the modules that unlock the disk. Naming
# them turns a missing cryptsetup/dmsetup into a hard dracut error instead of a
# boot-time emergency shell.
ADD_MODULES="bootc crypt dm"

# tpm2-tss/pcsc are omitted where their userspace is absent, and dracut treats a
# requested-but-unsatisfiable module as fatal rather than skipping it:
#   dracut[E]: Module 'tpm2-tss' cannot be installed.
# Ubuntu installs the TPM2 userspace instead and only omits pcsc, so probe
# rather than hardcoding either list.
OMIT_MODULES=""
command -v tpm2_pcrread >/dev/null 2>&1 || OMIT_MODULES="${OMIT_MODULES} tpm2-tss"
command -v pcscd >/dev/null 2>&1 || OMIT_MODULES="${OMIT_MODULES} pcsc"

# Built with explicit `if`s rather than `cond && echo`: under `set -e` an
# AND-OR list whose left side fails is the group's exit status, so an image
# with nothing to omit and no modules to add could take the whole build down
# depending on the bash version.
{
	echo "reproducible=yes"
	echo "hostonly=no"
	echo "compress=zstd"
	echo "add_dracutmodules+=\" ${ADD_MODULES} \""
	if [[ -n "$OMIT_MODULES" ]]; then
		echo "omit_dracutmodules+=\"${OMIT_MODULES} \""
	fi
	if ((${#DRIVERS[@]})); then
		echo "add_drivers+=\" ${DRIVERS[*]} \""
	fi
} >"${CONF_DIR}/30-bootc-container-build.conf"

echo "--- ${CONF_DIR}/30-bootc-container-build.conf ---"
cat "${CONF_DIR}/30-bootc-container-build.conf"
printf "::endgroup::\n"
