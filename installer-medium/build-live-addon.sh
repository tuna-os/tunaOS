#!/usr/bin/env bash
# Build a live UKI addon for systemd-boot cells (tunaOS#4913).
#
# Usage: installer-medium/build-live-addon.sh OUT.ADDON.EFI [--dry-run]
#
# Builds an unsigned addon carrying the live kernel command line fragment
# (tunaos.live), GNOME OS's live.addon.efi pattern: the medium carries it,
# the installer copies only the main UKI. Signing is CI's job: set
# UKIFY_SIGNTOOL, UKIFY_KEY and UKIFY_CERT and the script passes them to
# ukify. With --dry-run, print the ukify command and exit 0.
set -euo pipefail

OUT="${1:?usage: build-live-addon.sh OUT.ADDON.EFI [--dry-run]}"
DRY_RUN="${2:-}"

args=(build "--cmdline=tunaos.live" "--output=${OUT}")
if [[ -n "${UKIFY_SIGNTOOL:-}" ]]; then
	args+=(--signtool "${UKIFY_SIGNTOOL}")
fi
if [[ -n "${UKIFY_KEY:-}" && -n "${UKIFY_CERT:-}" ]]; then
	args+=(--secureboot-private-key "${UKIFY_KEY}" --secureboot-certificate "${UKIFY_CERT}")
fi

echo "ukify ${args[*]}"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "(dry run: no addon built)"
	exit 0
fi
ukify "${args[@]}"
