#!/usr/bin/env bash
# Final per-variant bootc step: build the initramfs, bootcify the rootfs, and
# validate. Runs after the desktop packages are installed, as the last layer of
# each variant stage.
#
# Expects the build context bind-mounted at /run/context.
set -xeuo pipefail

CTX="${CTX:-/run/context}"

# Build a reproducible, non-host-specific initramfs (the bootc dracut module is
# pulled in via the sandbox dracut.conf.d drop-ins) for the installed kernel.
KVER_DIR="$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1)"
dracut --force --zstd --reproducible --no-hostonly "${KVER_DIR}/initramfs.img"

# Bootcify: wipe /var and lay the composefs-backed bootc filesystem. apt is
# unusable after this point.
"${CTX}/build_scripts/bootc/mount-system.sh"

# https://bootc-dev.github.io/bootc/bootc-images.html#standard-metadata-for-bootc-compatible-images
# (the LABEL is set in the Containerfile; lint validates the whole image).
# /root is now a bind-mount target that does not exist at build time, so point
# HOME at /tmp for the lint invocation.
HOME=/tmp bootc container lint
