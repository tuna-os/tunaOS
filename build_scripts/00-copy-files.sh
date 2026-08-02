#!/usr/bin/env bash

set -euo pipefail
echo "Running file copy with BASE_IMAGE=${BASE_IMAGE}"
if [[ -f /etc/os-release ]]; then
	if ! grep -q '^BASE_IMAGE=' /etc/os-release 2>/dev/null; then
		echo "BASE_IMAGE=\"${BASE_IMAGE}\"" >>/etc/os-release || true
	fi
elif [[ -f /usr/lib/os-release ]]; then
	if ! grep -q '^BASE_IMAGE=' /usr/lib/os-release 2>/dev/null; then
		echo "BASE_IMAGE=\"${BASE_IMAGE}\"" >>/usr/lib/os-release || true
	fi
fi
source /run/context/build_scripts/lib.sh

echo "$BASE_IMAGE"
cat /etc/os-release

printf "::group:: === Base File Copying ===\n"
cp -rvf "/run/context/files/." / || cp -rf "/run/context/files/." / || true
printf "::endgroup::\n"
