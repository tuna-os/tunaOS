#!/usr/bin/env bash
# Fetch the bootc-installer Flatpak pinned by image-versions.yaml and verify it
# before making it visible to the live-image customization lifecycle.
set -euo pipefail

VERSIONS_FILE="${1:?usage: fetch-installer-bundle.sh VERSIONS_FILE OUTPUT [ARCH]}"
OUTPUT="${2:?usage: fetch-installer-bundle.sh VERSIONS_FILE OUTPUT [ARCH]}"
ARCH="${3:-$(uname -m)}"

read_download() {
	local key="$1"
	sed -n "s/^  ${key}:[[:space:]]*\"\([^\"]*\)\"[[:space:]]*$/\1/p" "$VERSIONS_FILE" | head -1
}

read_installer_checksum() {
	local arch="$1"
	sed -n "/^  bootc_installer_sha256:$/,/^  [[:alnum:]_][[:alnum:]_]*:/ {
		s/^    ${arch}:[[:space:]]*\"\([0-9a-f]\{64\}\)\"[[:space:]]*$/\1/p
	}" "$VERSIONS_FILE" | head -1
}

INSTALLER_VERSION="$(read_download bootc_installer)"
case "$ARCH" in
x86_64)
	INSTALLER_ASSET="org.bootcinstaller.Installer.flatpak"
	;;
aarch64)
	INSTALLER_ASSET="org.bootcinstaller.Installer-aarch64.flatpak"
	;;
*)
	echo "ERROR: bootc-installer publishes no pinned asset for ${ARCH}" >&2
	exit 1
	;;
esac
INSTALLER_SHA256="$(read_installer_checksum "$ARCH")"

if [[ ! "$INSTALLER_VERSION" =~ ^v[0-9A-Za-z._-]+$ ]]; then
	echo "ERROR: downloads.bootc_installer is missing or invalid in ${VERSIONS_FILE}" >&2
	exit 1
fi
if [[ ! "$INSTALLER_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
	echo "ERROR: downloads.bootc_installer_sha256.${ARCH} is missing or invalid in ${VERSIONS_FILE}" >&2
	exit 1
fi

URL="https://github.com/tuna-os/bootc-installer/releases/download/${INSTALLER_VERSION}/${INSTALLER_ASSET}"
PART="${OUTPUT}.part"
rm -f "$OUTPUT" "$PART"
trap 'rm -f "$PART"' EXIT

curl --retry 3 --fail --location --max-time 300 "$URL" -o "$PART"
printf '%s  %s\n' "$INSTALLER_SHA256" "$PART" | sha256sum --check --strict
mv "$PART" "$OUTPUT"
trap - EXIT

echo "Verified bootc-installer ${INSTALLER_VERSION} (${ARCH})"
