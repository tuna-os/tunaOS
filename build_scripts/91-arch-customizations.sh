#!/usr/bin/env bash

set -euo pipefail
printf "::group:: === Arch Customizations ===\n"

source /run/context/build_scripts/lib.sh 2>/dev/null || true

ARCH_NAME="$(uname -m 2>/dev/null || echo "x86_64")"

if [ -d "/run/context/overrides/${ARCH_NAME}" ]; then
	copy_systemfiles_for "${ARCH_NAME}" || true
	run_buildscripts_for "${ARCH_NAME}" || true
else
	echo "No architecture overrides for '${ARCH_NAME}', skipping."
fi

printf "::endgroup::\n"
