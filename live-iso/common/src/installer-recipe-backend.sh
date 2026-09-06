#!/usr/bin/env bash
# Decide the three on-disk-layout keys the installer recipe has to carry, by
# PROBING THE IMAGE rather than guessing from its name.
#
#   bootloader        grub2 | systemd
#   composeFsBackend  false | true
#   filesystem        xfs   | ext4
#
# Echoes three `KEY=value` lines and exits non-zero if the image cannot be
# classified. Extracted from customize-live.sh so the decision is unit-testable
# against fixture trees (tests/bats/test_installer_recipe_backend.bats) — the
# branches below are the difference between a bootable disk and a dracut
# emergency shell, and they were previously not exercised by anything.
#
# Usage: installer-recipe-backend.sh [sysroot]   (default "", i.e. the live root)
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

if [[ "$backend" == "composefs-native" ]]; then
	echo "bootloader=systemd"
	echo "composeFsBackend=true"
else
	echo "bootloader=grub2"
	echo "composeFsBackend=false"
fi
echo "filesystem=${filesystem}"
