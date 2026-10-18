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

case "$(uname -m)" in
x86_64) UUPD_ARCH="x86_64" ;;
aarch64) UUPD_ARCH="arm64" ;;
*)
	echo "uupd: unsupported architecture: $(uname -m)" >&2
	exit 1
	;;
esac

UUPD_TMPDIR="$(mktemp -d)"
trap 'rm -rf "$UUPD_TMPDIR"' EXIT
UUPD_SRC_BASE="https://raw.githubusercontent.com/ublue-os/uupd/${UUPD_VERSION}"

curl --retry 3 --fail --silent --show-error --location \
	-o "$UUPD_TMPDIR/uupd.tar.gz" \
	"https://github.com/ublue-os/uupd/releases/download/${UUPD_VERSION}/uupd_Linux_${UUPD_ARCH}.tar.gz"
tar -xzf "$UUPD_TMPDIR/uupd.tar.gz" -C "$UUPD_TMPDIR" uupd
for UUPD_UNIT in uupd.service uupd.timer uupd-manual.service; do
	curl --retry 3 --fail --silent --show-error --location \
		-o "$UUPD_TMPDIR/$UUPD_UNIT" "${UUPD_SRC_BASE}/${UUPD_UNIT}"
	[[ -s "$UUPD_TMPDIR/$UUPD_UNIT" ]]
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
