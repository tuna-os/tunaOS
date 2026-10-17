#!/usr/bin/env bash
# Install the pinned uupd binary and its upstream systemd units.
#
# The release archive contains only the binary. The unit files live beside the
# source tag, so install both from the same pinned release. This is kept
# separate from the numbered package phase because Containerfile.arch does not
# run build_scripts/10-base-packages.sh.
set -euo pipefail

UUPD_CONTEXT="${UUPD_CONTEXT:-/run/context}"
UUPD_ROOT="${UUPD_ROOT:-/}"
UUPD_ROOT="${UUPD_ROOT%/}"
[[ -n "$UUPD_ROOT" ]] || UUPD_ROOT="/"
UUPD_VERSIONS_FILE="${UUPD_VERSIONS_FILE:-${UUPD_CONTEXT}/image-versions.yaml}"

if [[ ! -f "$UUPD_VERSIONS_FILE" ]]; then
	echo "uupd: version file not found: $UUPD_VERSIONS_FILE" >&2
	exit 1
fi

UUPD_VERSION="$(sed -nE 's/^[[:space:]]*uupd:[[:space:]]*"([^"]+)".*/\1/p' "$UUPD_VERSIONS_FILE")"
if [[ ! "$UUPD_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	echo "uupd: invalid version in $UUPD_VERSIONS_FILE" >&2
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

UUPD_SRC_BASE="https://raw.githubusercontent.com/ublue-os/uupd/${UUPD_VERSION}"
UUPD_RELEASE_BASE="https://github.com/ublue-os/uupd/releases/download/${UUPD_VERSION}"
UUPD_TMPDIR="$(mktemp -d)"
trap 'rm -rf "$UUPD_TMPDIR"' EXIT

curl --retry 3 --fail --silent --show-error --location \
	-o "$UUPD_TMPDIR/uupd.tar.gz" \
	"${UUPD_RELEASE_BASE}/uupd_Linux_${UUPD_ARCH}.tar.gz"
tar -xzf "$UUPD_TMPDIR/uupd.tar.gz" -C "$UUPD_TMPDIR" uupd
install -Dm0755 "$UUPD_TMPDIR/uupd" "$UUPD_ROOT/usr/bin/uupd"

for UUPD_UNIT in uupd.service uupd.timer uupd-manual.service; do
	curl --retry 3 --fail --silent --show-error --location \
		-o "$UUPD_TMPDIR/$UUPD_UNIT" \
		"${UUPD_SRC_BASE}/${UUPD_UNIT}"
	install -Dm0644 "$UUPD_TMPDIR/$UUPD_UNIT" \
		"$UUPD_ROOT/usr/lib/systemd/system/$UUPD_UNIT"
done

"$UUPD_ROOT/usr/bin/uupd" --help >/dev/null
printf 'uupd %s (%s) installed\n' "$UUPD_VERSION" "$UUPD_ARCH"
