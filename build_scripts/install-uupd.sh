#!/usr/bin/env bash
# Install uupd and its upstream units from the same image-versions.yaml pin.
# Arch skips the numbered package phase, so it calls this installer directly.
set -euo pipefail

# Overrides allow a real-download smoke into a disposable root, without writing
# to the host's /usr or running an update. Normal image builds use /run/context.
UUPD_CONTEXT="${UUPD_CONTEXT:-/run/context}"
UUPD_ROOT="${UUPD_ROOT:-/}"
UUPD_VERSIONS_FILE="${UUPD_CONTEXT}/image-versions.yaml"

if [[ ! -f "$UUPD_VERSIONS_FILE" ]]; then
	echo "uupd: version file not found: $UUPD_VERSIONS_FILE" >&2
	exit 1
fi
UUPD_VERSION="$(sed -nE 's/^[[:space:]]*uupd:[[:space:]]*"([^"]+)".*/\1/p' "$UUPD_VERSIONS_FILE")"
if [[ ! "$UUPD_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	echo "uupd: missing or invalid version in $UUPD_VERSIONS_FILE" >&2
	exit 1
fi

read_checksum() {
	local arch="$1"
	sed -n "/^[[:space:]]*uupd_sha256:/,/^[^[:space:]]/ {
		s/^[[:space:]]*${arch}:[[:space:]]*\"\([0-9a-f]\{64\}\)\".*/\1/p
	}" "$UUPD_VERSIONS_FILE" | head -1
}

read_unit_checksum() {
	local unit="$1"
	sed -n "/^[[:space:]]*uupd_units_sha256:/,/^[^[:space:]]/ {
		s/^[[:space:]]*${unit}:[[:space:]]*\"\([0-9a-f]\{64\}\)\".*/\1/p
	}" "$UUPD_VERSIONS_FILE" | head -1
}

ARCH="$(uname -m)"
case "$ARCH" in
x86_64) UUPD_ARCH="x86_64" ;;
aarch64) UUPD_ARCH="arm64" ;;
*)
	echo "uupd: unsupported architecture: $ARCH" >&2
	exit 1
	;;
esac

UUPD_SHA256="$(read_checksum "$ARCH")"
if [[ -z "$UUPD_SHA256" && "$ARCH" == "aarch64" ]]; then
	UUPD_SHA256="$(read_checksum "arm64")"
fi
if [[ ! "$UUPD_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
	echo "uupd: missing or invalid checksum for $ARCH in $UUPD_VERSIONS_FILE" >&2
	exit 1
fi

UUPD_TMPDIR="$(mktemp -d)"
trap 'rm -rf "$UUPD_TMPDIR"' EXIT
UUPD_SRC_BASE="https://raw.githubusercontent.com/ublue-os/uupd/${UUPD_VERSION}"

curl --retry 3 --fail --silent --show-error --location \
	-o "$UUPD_TMPDIR/uupd.tar.gz" \
	"https://github.com/ublue-os/uupd/releases/download/${UUPD_VERSION}/uupd_Linux_${UUPD_ARCH}.tar.gz"
printf '%s  %s\n' "$UUPD_SHA256" "$UUPD_TMPDIR/uupd.tar.gz" | sha256sum --check --strict
tar -xzf "$UUPD_TMPDIR/uupd.tar.gz" -C "$UUPD_TMPDIR" uupd
for UUPD_UNIT in uupd.service uupd.timer uupd-manual.service; do
	UUPD_UNIT_SHA256="$(read_unit_checksum "$UUPD_UNIT")"
	if [[ ! "$UUPD_UNIT_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
		echo "uupd: missing or invalid checksum for unit $UUPD_UNIT in $UUPD_VERSIONS_FILE" >&2
		exit 1
	fi
	curl --retry 3 --fail --silent --show-error --location \
		-o "$UUPD_TMPDIR/$UUPD_UNIT" "${UUPD_SRC_BASE}/${UUPD_UNIT}"
	printf '%s  %s\n' "$UUPD_UNIT_SHA256" "$UUPD_TMPDIR/$UUPD_UNIT" | sha256sum --check --strict
done

# Stage every download before replacing the image's binary or units.
install -Dm0755 "$UUPD_TMPDIR/uupd" "${UUPD_ROOT%/}/usr/bin/uupd"
for UUPD_UNIT in uupd.service uupd.timer uupd-manual.service; do
	install -Dm0644 "$UUPD_TMPDIR/$UUPD_UNIT" \
		"${UUPD_ROOT%/}/usr/lib/systemd/system/$UUPD_UNIT"
done

# Cobra handles --help without invoking uupd's update command. Never run uupd
# without this flag during image construction: its default action updates OSes.
"${UUPD_ROOT%/}/usr/bin/uupd" --help >/dev/null
printf 'uupd %s (%s) installed\n' "$UUPD_VERSION" "$UUPD_ARCH"
