#!/usr/bin/env bash
# install-oras.sh VERSION ARCH — install a checksum-verified ORAS CLI.
#
# The release archive is downloaded to a temp dir, checked against the pinned
# SHA-256 below, and only then extracted. An unknown version/arch pair or a
# digest mismatch fails closed before anything is extracted or run as root.
#
# The digests come from upstream's oras_<ver>_checksums.txt release asset and
# were re-derived from the downloaded archives (tunaOS#3336). To add a version,
# download the archive, compare sha256sum with that checksums file, add a row.
set -euo pipefail

version="${1:?usage: install-oras.sh VERSION ARCH (e.g. 1.2.0 amd64)}"
arch="${2:?usage: install-oras.sh VERSION ARCH (e.g. 1.2.0 amd64)}"

case "${version}_${arch}" in
1.2.0_amd64) sha256="5b3f1cbb86d869eee68120b9b45b9be983f3738442f87ee5f06b00edd0bab336" ;;
1.2.0_arm64) sha256="27df680a39fc2fcedc549cb737891623bc696c9a92a03fd341e9356a35836bae" ;;
1.3.0_amd64) sha256="6cdc692f929100feb08aa8de584d02f7bcc30ec7d88bc2adc2054d782db57c64" ;;
*)
	echo "install-oras.sh: no pinned SHA-256 for ORAS ${version} linux_${arch}" >&2
	exit 1
	;;
esac

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

archive="oras_${version}_linux_${arch}.tar.gz"
curl -fsSL "https://github.com/oras-project/oras/releases/download/v${version}/${archive}" \
	-o "${tmp}/${archive}"
printf '%s  %s\n' "$sha256" "${tmp}/${archive}" | sha256sum -c -
tar -xzf "${tmp}/${archive}" -C "$tmp" oras
sudo install -m 0755 "${tmp}/oras" /usr/local/bin/oras
oras version
