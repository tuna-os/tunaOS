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
dracut --force --zstd --reproducible --no-hostonly "${KVER_DIR}/initramfs.img"

# Bootcify: wipe /var and lay the composefs-backed bootc filesystem. apt is
# unusable after this point.
"${CTX}/build_scripts/bootc/mount-system.sh"

# mount-system.sh wipes /var (composefs layout). Recreate /var/tmp so
# downstream tooling (tacklebox ISO initramfs, build scripts) doesn't fail
# with "realpath: /var/tmp: No such file or directory".
mkdir -p /var/tmp

# Validate the bootcified image. Non-fatal (mirrors cleanup.sh's lint_image) —
# set BOOTC_LINT_FATAL=1 to enforce. /root is now a bind-mount target absent at
# build time, so point HOME at /tmp.
if ! HOME=/tmp bootc container lint; then
	if [[ "${BOOTC_LINT_FATAL:-0}" == "1" ]]; then
		exit 1
	fi
	echo "::warning::bootc container lint reported findings on bootcified ${IMAGE_NAME:-grouper} (non-fatal)"
fi
