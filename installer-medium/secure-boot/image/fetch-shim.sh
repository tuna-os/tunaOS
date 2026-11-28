#!/usr/bin/env bash
# Put the pinned shim and MokManager into a directory (tunaOS#4955).
#
# Usage: fetch-shim.sh OUTDIR
#
# Reads the pin in shim.toml, as sign-image.sh does for an image: download
# the RPM (or take SB_SHIM_RPM, a local copy), check its sha256, and write
# OUTDIR/shim<arch>.efi and OUTDIR/mm<arch>.efi byte for byte. The medium
# build uses it for a tunaos-key cell whose image does not carry the files:
# a composefs medium does not show /usr of the image on its mounted root.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:?usage: fetch-shim.sh OUTDIR}"
ARCH="${SB_ARCH:-x64}"

mapfile -t PIN < <(
	python3 - "${HERE}/shim.toml" "${ARCH}" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    pin = tomllib.load(handle)["shim"].get(sys.argv[2])
if pin is None:
    raise SystemExit(f"fetch-shim: no shim pin for {sys.argv[2]}")
for key in ("url", "sha256", "shim", "mok_manager"):
    print(pin[key])
PY
)
[[ ${#PIN[@]} -eq 4 ]] || exit 1
WORK="$(mktemp -d)"
trap 'rm -rf -- "${WORK}"' EXIT
RPM="${SB_SHIM_RPM:-}"
if [[ -z "${RPM}" ]]; then
	RPM="${WORK}/shim.rpm"
	curl --fail --silent --show-error --location --retry 3 --output "${RPM}" "${PIN[0]}"
fi
[[ "$(sha256sum "${RPM}" | cut -d' ' -f1)" = "${PIN[1]}" ]] || {
	echo "fetch-shim: the shim RPM differs from the sha256 in shim.toml" >&2
	exit 1
}
mkdir -p "${WORK}/x" "${OUT}"
if command -v bsdtar >/dev/null; then
	bsdtar -xf "${RPM}" -C "${WORK}/x" "./${PIN[2]}" "./${PIN[3]}"
else
	(cd "${WORK}/x" && rpm2cpio "${RPM}" | cpio -idm --quiet "./${PIN[2]}" "./${PIN[3]}")
fi
install -m 0644 "${WORK}/x/${PIN[2]}" "${OUT}/shim${ARCH}.efi"
install -m 0644 "${WORK}/x/${PIN[3]}" "${OUT}/mm${ARCH}.efi"
echo "fetch-shim: ${OUT}/shim${ARCH}.efi and mm${ARCH}.efi from $(basename "${PIN[0]}")"
