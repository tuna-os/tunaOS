#!/usr/bin/env bash
# Per-VARIANT system-file overrides.
#
# 91-arch-customizations.sh does this for the architecture; there was no
# equivalent for the variant, even though 00-tunaos.toml explicitly directs
# per-variant install settings to "a higher-sorting drop-in (e.g.
# 50-<variant>.toml)". There was nowhere to put one.
#
# hummingbird is why. It probes BACKEND=ostree SEALED=0, so it takes the
# xfs root from 00-tunaos.toml, and then `bootc install to-disk` ABORTS:
# BIOS grub2-install cannot read the xfs this base's mkfs.xfs produces, and
# bootupctl installs the BIOS component unconditionally, so the whole disk
# install fails on UEFI hardware too. Six consecutive nightly Gates died on
# it (tunaOS run 32786338463, gnome Gate job 97638679623), which is why
# hummingbird:gnome has never been promoted.

set -euo pipefail
printf "::group:: === Variant Customizations ===\n"

source /run/context/build_scripts/lib.sh 2>/dev/null || true

# IMAGE_NAME_VARIANT is the variant id, passed as a build arg by
# scripts/build-image-inner.sh and exported as ENV by the Containerfile.
# canonical_variant folds aliases (bonito-rawhide -> bonito, etc.) the same
# way 90-image-info.sh does.
VARIANT_KEY="${IMAGE_NAME_VARIANT:-}"
if command -v canonical_variant >/dev/null 2>&1 && [ -n "${VARIANT_KEY}" ]; then
	VARIANT_KEY="$(canonical_variant "${VARIANT_KEY}")"
fi

if [ -z "${VARIANT_KEY}" ]; then
	# Loud, not silent. A build that cannot name its own variant would
	# skip every per-variant override while looking perfectly healthy —
	# the exact failure mode that let hummingbird ship a broken installer
	# for six nights.
	echo "ERROR: IMAGE_NAME_VARIANT is unset; cannot apply per-variant overrides." >&2
	echo "  It is passed by scripts/build-image-inner.sh as --build-arg and must" >&2
	echo "  be declared ARG + ENV in the Containerfile to reach this script." >&2
	exit 1
fi

echo "variant key: ${VARIANT_KEY}"
if [ -d "/run/context/overrides/${VARIANT_KEY}" ]; then
	copy_systemfiles_for "${VARIANT_KEY}" || true
	run_buildscripts_for "${VARIANT_KEY}" || true
else
	echo "No variant overrides for '${VARIANT_KEY}', skipping."
fi

printf "::endgroup::\n"
