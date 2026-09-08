#!/usr/bin/env bash
# Install the pinned DMS application payload when an RPM only ships the
# runtime-sync launcher. AvengeMedia's EL10 dms-greeter 1.6 RPM contains no
# QML, so an offline image otherwise reaches greetd without a usable greeter.
#
# This mirrors the source payload used by tunaos-packages. Once that repository
# publishes an EL10 dms-greeter containing DMSGreeter.qml, the caller skips this
# fallback and the RPM remains authoritative.
set -euo pipefail

[[ -f /usr/share/quickshell/dms-greeter/DMSGreeter.qml ]] && exit 0

VERSIONS="${VERSIONS_FILE:-/run/context/image-versions.yaml}"
read_version() {
	local key="$1"
	sed -n "s/^[[:space:]]*${key}:[[:space:]]*\"\{0,1\}\([^\"]*\)\"\{0,1\}[[:space:]]*$/\1/p" "$VERSIONS" | head -1
}

DMS_QML_VERSION="${DMS_QML_VERSION:-$(read_version dms_qml)}"
DMS_QML_SHA256="${DMS_QML_SHA256:-$(read_version dms_qml_sha256)}"
[[ -n "$DMS_QML_VERSION" && -n "$DMS_QML_SHA256" ]] || {
	echo "ERROR: downloads.dms_qml and dms_qml_sha256 must be pinned in $VERSIONS" >&2
	exit 1
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ARCHIVE="$TMP/dms-qml.tar.gz"
SRC="$TMP/src"
mkdir "$SRC"

curl -fsSL --retry 3 \
	"https://github.com/AvengeMedia/DankMaterialShell/releases/download/${DMS_QML_VERSION}/dms-qml.tar.gz" \
	-o "$ARCHIVE"
printf '%s  %s\n' "$DMS_QML_SHA256" "$ARCHIVE" | sha256sum --check --strict
tar --no-same-owner -xzf "$ARCHIVE" -C "$SRC"

[[ -f "$SRC/DMSGreeter.qml" && -x "$SRC/Modules/Greetd/assets/dms-greeter" ]] || {
	echo "ERROR: DMS ${DMS_QML_VERSION} archive lacks its greeter payload" >&2
	exit 1
}

# Match the tunaos-packages dms and dms-greeter recipes: both packages install
# the release's complete QML tree, under the paths Quickshell resolves.
rm -rf /usr/share/dankmaterialshell /usr/share/quickshell/dms-greeter
install -d /usr/share/dankmaterialshell /usr/share/quickshell/dms-greeter
cp -a "$SRC/." /usr/share/dankmaterialshell/
cp -a "$SRC/." /usr/share/quickshell/dms-greeter/
install -Dm0755 "$SRC/Modules/Greetd/assets/dms-greeter" /usr/bin/dms-greeter

echo "==> Installed pinned DMS ${DMS_QML_VERSION} QML fallback"
