#!/usr/bin/env bash
# Decide the three on-disk-layout keys the installer recipe has to carry, by
# PROBING THE IMAGE rather than guessing from its name.
#
#   bootloader        grub2 | systemd
#   composeFsBackend  false | true
#   filesystem        xfs   | ext4   (| btrfs, opt-in only, see below)
#
# Echoes three `KEY=value` lines and exits non-zero if the image cannot be
# classified. Extracted from customize-live.sh so the decision is unit-testable
# against fixture trees (tests/bats/test_installer_recipe_backend.bats) — the
# branches below are the difference between a bootable disk and a dracut
# emergency shell, and they were previously not exercised by anything.
#
# Usage: installer-recipe-backend.sh [sysroot]   (default "", i.e. the live root)
#
# btrfs (tuna-os/tunaOS#4906, epic #4905) is OFF by default. Set
# TUNAOS_INSTALLER_ALLOW_BTRFS=1 to let the probe emit it. The pinned fisherman
# accepts `filesystem: btrfs` (recipe.Filesystems, FormatRoot), but the ISO +
# fisherman LUKS end-to-end test has not passed on btrfs for any cell yet, and
# #4906 makes that the precondition for changing the default. Unset, the output
# is byte-identical to before. With the variable set, the rules are:
#   1. EL family (ID or ID_LIKE has rhel, centos, almalinux, rocky or ol) keeps
#      its xfs/ext4 result. EL10 has no btrfs. hummingbird has ID_LIKE
#      "fedora rhel", so it stays here until its own check (#4906).
#   2. Only a positively known non-EL family gets btrfs: ID or ID_LIKE has
#      fedora, arch, opensuse/suse, ubuntu, debian or gentoo. No os-release,
#      or an unknown family, keeps the old result. Never guessed.
#   3. A composefs image (sealed pin, or composefs-native backend) needs the
#      fs-verity fix 254e15591ee4 (mainline v7.4-rc2). It gets btrfs only if
#      EVERY kernel in usr/lib/modules/ is >= 7.4-rc2 by release string, else
#      ext4. A backport to an older stable kernel is not detectable from the
#      version, so such an image stays on ext4 until the rule is widened.
#      An image with no usr/lib/modules/ entry also stays on ext4.
#
# This is a faithful port of TUNAOS_BACKEND_PROBE_SH in scripts/lib/common.sh.
# THE ORDER IS LOAD-BEARING and is documented at length there; the short form:
# bootupd payload is checked FIRST so that a composefs-SEALED image which still
# ships bootupd stays on the ostree path.

set -euo pipefail

SYSROOT="${1:-}"

# Sealing is read once and used twice — it selects the filesystem on its own,
# and it is branch 2 of the backend decision. They are genuinely separate
# questions: `ostree` + sealed is a real combination (see common.sh), and
# keying the filesystem off the backend would get exactly those images wrong.
composefs_enabled=0
if grep -A8 '^\[composefs\]' "${SYSROOT}/usr/lib/ostree/prepare-root.conf" 2>/dev/null |
	grep -qiE 'enabled[[:space:]]*=[[:space:]]*(yes|true|1|signed)'; then
	composefs_enabled=1
fi

# bootupd 0.2.x kept binaries under updates/EFI/<vendor>; current Fedora keeps
# versioned binaries under /usr/lib/efi with only EFI.json under bootupd/
# updates — hence the two-form test.
#
# THE EFI BINARY NAMES ARE GLOBBED, NOT SPELLED OUT, because the suffix is the
# EFI architecture: grubx64/shimx64/systemd-bootx64 on x86_64, and
# grubaa64/shimaa64/systemd-bootaa64 on aarch64. Spelling out the x64 forms
# made this probe silently unclassifiable on every arm64 image, which is not a
# theoretical concern — albacore:kde-linux-arm64 ships a complete legacy
# bootupd payload
#   /usr/lib/bootupd/updates/EFI/almalinux/{grubaa64,shimaa64}.efi
# and still fell all the way through to the "cannot determine the bootc
# backend" exit, failing the arm64 ISO build while the amd64 leg of the same
# cell passed. The question each branch asks — "is there a GRUB EFI binary in
# the bootupd payload?", "is there a systemd-boot EFI binary?" — was never
# architecture-specific; only the spelling was.
if ls "${SYSROOT}"/usr/lib/bootupd/updates/EFI/*/grub*.efi >/dev/null 2>&1 ||
	{ [[ -f "${SYSROOT}/usr/lib/bootupd/updates/EFI.json" ]] &&
		find "${SYSROOT}/usr/lib/efi/grub2" -type f -name 'grub*.efi' -print -quit 2>/dev/null | grep -q . &&
		find "${SYSROOT}/usr/lib/efi/shim" -type f -name 'shim*.efi' -print -quit 2>/dev/null | grep -q .; }; then
	backend="ostree"
elif [[ "$composefs_enabled" == "1" ]]; then
	# Reaching here means there is NO bootupd payload, so an ostree install is
	# impossible: bootc aborts with
	#   error: Installing to disk: bootupd is required for ostree-based installs
	backend="composefs-native"
elif find "${SYSROOT}/usr/lib/systemd/boot/efi" -type f -name 'systemd-boot*.efi' -print -quit 2>/dev/null | grep -q .; then
	backend="composefs-native"
else
	# Never guessed. A wrong guess in either direction is an unbootable disk,
	# and the failure surfaces minutes later with nothing in the log that
	# points back here.
	echo "ERROR: cannot determine the bootc backend of this image." >&2
	echo "       No bootupd payload, no composefs pin in prepare-root.conf," >&2
	echo "       and no systemd-boot EFI binary." >&2
	exit 1
fi

# A composefs-sealed rootfs is verified with fs-verity. XFS has no fs-verity,
# so a sealed image installed onto XFS fails initrd-switch-root and drops to a
# dracut emergency shell — see the warning in
# system_files/usr/lib/bootc/install/00-tunaos.toml. ext4 is the proven sealed
# filesystem; btrfs has fs-verity but its ostree deployment fails to mount
# (wootc#35). scripts/build-qcow2.sh has always done this for the Gate's disk
# image; the ISO install path and the GUI recipe did not, which is the
# disagreement this file exists to end.
if [[ "$composefs_enabled" == "1" ]]; then
	filesystem="ext4"
else
	filesystem="xfs"
fi

# ── btrfs on non-EL bases (opt-in, #4906) ────────────────────────────────────
# Reads os-release the way the rest of the repo does: ID and ID_LIKE words.
os_family_words() {
	local f="${SYSROOT}/usr/lib/os-release"
	[[ -f "$f" ]] || f="${SYSROOT}/etc/os-release"
	[[ -f "$f" ]] || return 0
	(
		ID="" ID_LIKE=""
		# shellcheck disable=SC1090
		. "$f" 2>/dev/null || true
		echo "${ID} ${ID_LIKE}"
	)
}

has_word() { # has_word "<words>" pattern...
	local words=" $1 " w
	shift
	for w in "$@"; do [[ "$words" == *" ${w} "* ]] && return 0; done
	return 1
}

# True when release string $1 is >= 7.4-rc2 (fs-verity fix 254e15591ee4).
# Release strings look like 7.4.0-rc2.fc45.x86_64 or 7.5.1-200.fc45.x86_64.
kernel_release_has_verity_fix() {
	local rel="$1" re='^([0-9]+)\.([0-9]+)'
	[[ "$rel" =~ $re ]] || return 1
	local major="${BASH_REMATCH[1]}" minor="${BASH_REMATCH[2]}"
	((major > 7)) && return 0
	((major < 7)) && return 1
	((minor > 4)) && return 0
	((minor < 4)) && return 1
	# 7.4: only the -rcN pre-releases before rc2 lack the fix.
	local rc='^[0-9]+\.[0-9]+(\.[0-9]+)?[-.](0\.)?rc([0-9]+)'
	if [[ "$rel" =~ $rc ]]; then
		((BASH_REMATCH[3] >= 2))
		return
	fi
	return 0
}

all_kernels_have_verity_fix() {
	local d found=0
	for d in "${SYSROOT}"/usr/lib/modules/*/; do
		[[ -d "$d" ]] || continue
		found=1
		kernel_release_has_verity_fix "$(basename "$d")" || return 1
	done
	((found == 1))
}

if [[ "${TUNAOS_INSTALLER_ALLOW_BTRFS:-0}" == "1" ]]; then
	_words="$(os_family_words)"
	if has_word "$_words" rhel centos almalinux rocky ol; then
		: # EL family: no btrfs.
	elif has_word "$_words" fedora arch opensuse opensuse-tumbleweed opensuse-leap suse ubuntu debian gentoo; then
		if [[ "$composefs_enabled" == "1" || "$backend" == "composefs-native" ]]; then
			if all_kernels_have_verity_fix; then
				filesystem="btrfs"
			else
				filesystem="ext4"
			fi
		else
			filesystem="btrfs"
		fi
	fi
fi

if [[ "$backend" == "composefs-native" ]]; then
	echo "bootloader=systemd"
	echo "composeFsBackend=true"
else
	echo "bootloader=grub2"
	echo "composeFsBackend=false"
fi
echo "filesystem=${filesystem}"
