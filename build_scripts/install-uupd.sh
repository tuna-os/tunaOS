#!/usr/bin/env bash
# Install uupd and its upstream units from the same image-versions.yaml pin.
# Arch skips the numbered package phase, so it calls this installer directly.
set -euo pipefail

# Overrides allow a real-download smoke into a disposable root, without writing
# to the host's /usr or running an update. Normal image builds use /run/context.
UUPD_CONTEXT="${UUPD_CONTEXT:-/run/context}"
UUPD_ROOT="${UUPD_ROOT:-/}"
UUPD_VERSIONS_FILE="${UUPD_VERSIONS_FILE:-${UUPD_CONTEXT}/image-versions.yaml}"

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
x86_64)
	UUPD_ARCH="x86_64"
	;;
aarch64)
	UUPD_ARCH="arm64"
	;;
*)
	echo "uupd: unsupported architecture: $(uname -m)" >&2
	exit 1
	;;
esac

UUPD_SHA256="$(sed -n "/^[[:space:]]*uupd_sha256:/,/^[^ ]/p" "$UUPD_VERSIONS_FILE" |
	sed -nE "s/^[[:space:]]*${UUPD_ARCH}:[[:space:]]*\"?([0-9a-f]{64})\"?.*/\1/p" | head -1)"
if [[ -z "${UUPD_SHA256:-}" && "$UUPD_ARCH" == "arm64" ]]; then
	UUPD_SHA256="$(sed -n "/^[[:space:]]*uupd_sha256:/,/^[^ ]/p" "$UUPD_VERSIONS_FILE" |
		sed -nE "s/^[[:space:]]*aarch64:[[:space:]]*\"?([0-9a-f]{64})\"?.*/\1/p" | head -1)"
fi
if [[ ! "$UUPD_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
	echo "uupd: missing or invalid SHA-256 for ${UUPD_ARCH} in $UUPD_VERSIONS_FILE" >&2
	exit 1
fi

if [[ -z "${UUPD_REF:-}" ]]; then
	UUPD_REF="$(sed -nE 's/^[[:space:]]*uupd_ref:[[:space:]]*"([0-9a-f]{40})".*/\1/p' "$UUPD_VERSIONS_FILE")"
fi
if [[ -z "${UUPD_REF:-}" ]]; then
	case "$UUPD_VERSION" in
	v1.5.0) UUPD_REF="e5449438a4a50eb4988af88606ba131d78e2db81" ;;
	v1.5.1) UUPD_REF="9ebf7e1cb94deca3fe4cc76ef542dbc1c6190eaa" ;;
	esac
fi
if [[ ! "${UUPD_REF:-}" =~ ^[0-9a-f]{40}$ ]]; then
	echo "uupd: missing or invalid immutable commit ref (expected 40-hex SHA, got '${UUPD_REF:-}')" >&2
	exit 1
fi

uupd_unit_hash() {
	case "$1" in
	uupd.service) echo "${UUPD_SERVICE_SHA256:-65dd2b64dcb6a9f77227612aa624ef17fe43b32eb835b51d7d22a22755dc21a8}" ;;
	uupd.timer) echo "${UUPD_TIMER_SHA256:-bbb5f098ec33d047bdef571e0bc112364df157e0f92d73e0febab703c4a3c099}" ;;
	uupd-manual.service) echo "${UUPD_MANUAL_SERVICE_SHA256:-54d4bc5913b40463b178176d2654163111ea5ac952f88ede4d977fbb0905b5e6}" ;;
	*) return 1 ;;
	esac
}

UUPD_TMPDIR="$(mktemp -d)"
trap 'rm -rf "$UUPD_TMPDIR"' EXIT
UUPD_SRC_BASE="https://raw.githubusercontent.com/ublue-os/uupd/${UUPD_REF}"

curl --retry 3 --fail --silent --show-error --location \
	-o "$UUPD_TMPDIR/uupd.tar.gz" \
	"https://github.com/ublue-os/uupd/releases/download/${UUPD_VERSION}/uupd_Linux_${UUPD_ARCH}.tar.gz"

echo "${UUPD_SHA256}  ${UUPD_TMPDIR}/uupd.tar.gz" | sha256sum -c - >/dev/null
tar -xzf "$UUPD_TMPDIR/uupd.tar.gz" -C "$UUPD_TMPDIR" uupd

for UUPD_UNIT in uupd.service uupd.timer uupd-manual.service; do
	EXPECTED_UNIT_SHA="$(uupd_unit_hash "$UUPD_UNIT")"
	if [[ ! "$EXPECTED_UNIT_SHA" =~ ^[0-9a-f]{64}$ ]]; then
		echo "uupd: missing or invalid expected checksum for $UUPD_UNIT" >&2
		exit 1
	fi
	curl --retry 3 --fail --silent --show-error --location \
		-o "$UUPD_TMPDIR/$UUPD_UNIT" "${UUPD_SRC_BASE}/${UUPD_UNIT}"
	[[ -s "$UUPD_TMPDIR/$UUPD_UNIT" ]]
	echo "${EXPECTED_UNIT_SHA}  ${UUPD_TMPDIR}/$UUPD_UNIT" | sha256sum -c - >/dev/null
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
