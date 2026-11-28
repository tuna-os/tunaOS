#!/usr/bin/env bash
# Final per-variant bootc step: build the initramfs, bootcify the rootfs, and
# validate. Runs after the desktop packages are installed, as the last layer of
# each variant stage.
#
# Expects the build context bind-mounted at /run/context.
set -xeuo pipefail

CTX="${CTX:-/run/context}"

# cleanup.sh (in base-no-de) empties /var, removing /var/tmp; dracut needs a
# scratch tmpdir, so recreate it before building the initramfs.
mkdir -p /var/tmp

# Build a reproducible, non-host-specific initramfs (the bootc dracut module is
# pulled in via the sandbox dracut.conf.d drop-ins) for the installed kernel.
KVER_DIR="$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1)"
KVER="$(basename "${KVER_DIR}")"
# The variant's boot animation, selected before dracut copies it in.
"${CTX}/build_scripts/plymouth-set-theme.sh" ||
	echo "WARNING: plymouth-set-theme.sh failed; the distro boot splash stays" >&2
# Installs the 99tunaos-identity dracut module, so initrd-release reads
# "<Variant> (Initramfs)" and not dracut's "<Name> dracut-<ver> (Initramfs)"
# (tunaOS#4865; the Ubuntu bootc path never ran it).
"${CTX}/build_scripts/initrd-hostname.sh"
dracut --force --zstd --reproducible --no-hostonly "${KVER_DIR}/initramfs.img" "${KVER}"
# The build stops unless the initramfs carries the variant's own splash.
"${CTX}/build_scripts/checks/verify-plymouth-initramfs.sh" \
	"${IMAGE_NAME_VARIANT:-${IMAGE_NAME:-}}" "${KVER_DIR}/initramfs.img"
# 90-image-info.sh ran in base-no-de, so the initramfs must name the variant's
# DEFAULT_HOSTNAME, not the upstream fallback (tunaOS#4865).
"${CTX}/build_scripts/checks/verify-initrd-hostname.sh" "${KVER_DIR}/initramfs.img"
# The installed system unlocks its LUKS root with the TPM from the initramfs
# (tunaOS#5141).
"${CTX}/build_scripts/checks/verify-initramfs-tpm2.sh" "${KVER_DIR}/initramfs.img"

# Bootcify: wipe /var and lay the composefs-backed bootc filesystem. apt is
# unusable after this point.
"${CTX}/build_scripts/bootc/mount-system.sh"

# mount-system.sh wipes /var (composefs layout). Recreate /var/tmp so
# downstream tooling (tacklebox ISO initramfs, build scripts) doesn't fail
# with "realpath: /var/tmp: No such file or directory".
mkdir -p /var/tmp

# No machine-id in the image: an apt postinst committed one during the build,
# and every install from the image would share it (tunaOS#5103). Last, after
# every step that can run a postinst or systemd tool.
"${CTX}/build_scripts/checks/pristine-machine-id.sh"

# Validate the bootcified image. Non-fatal (mirrors cleanup.sh's lint_image) —
# set BOOTC_LINT_FATAL=1 to enforce. /root is now a bind-mount target absent at
# build time, so point HOME at /tmp.
if ! HOME=/tmp bootc container lint; then
	if [[ "${BOOTC_LINT_FATAL:-0}" == "1" ]]; then
		exit 1
	fi
	echo "::warning::bootc container lint reported findings on bootcified ${IMAGE_NAME:-grouper} (non-fatal)"
fi
