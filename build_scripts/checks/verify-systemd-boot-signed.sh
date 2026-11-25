#!/usr/bin/env bash
# Prove this Debian image ships a systemd-boot that Debian's shim accepts.
#
#   verify-systemd-boot-signed.sh [<efi-binary>]
#
# WHY THIS EXISTS (tunaOS#4955)
#
# The installer medium uses `distro-chain` Secure Boot for flounder and
# flounder-sid: Debian's shim starts the systemd-boot that Debian signed. The
# image shipped only the unsigned systemd-bootx64.efi, because apt satisfies
# `systemd-boot-efi-signed | systemd-boot-efi` with the unsigned package when
# the install list names it. This check fails the build unless the signed
# binary is present and its signature chains to the Debian Secure Boot CA.
#
# `sbverify --list` exits 0 on an unsigned file ("No signature table
# present"), so the check reads its output and not its exit status.
#
# The CA certificate is pinned next to this script. Its DER sha256 is the
# `.vendor_cert` of Debian's shim (shim-signed 1.51, trixie and sid, measured
# 2026-11-25). A changed pin stops the build.
#
# Without an argument the binary is
# /usr/lib/systemd/boot/efi/systemd-boot<arch>.efi.signed for the dpkg
# architecture. TUNAOS_SYSROOT points that path at a fixture tree (tests).
# TUNAOS_DEB_ARCH replaces `dpkg --print-architecture` (tests).

set -euo pipefail

CA_PEM="$(dirname "${BASH_SOURCE[0]}")/certs/debian-secure-boot-ca.pem"
CA_DER_SHA256="079646974bce09b1f04da67bd722d1fb0947ae4c4010bccdbba52d5b23cbf1a2"

die() {
	echo "ERROR: verify-systemd-boot-signed: $*" >&2
	exit 1
}

binary="${1:-}"
if [[ -z "$binary" ]]; then
	deb_arch="${TUNAOS_DEB_ARCH:-$(dpkg --print-architecture)}"
	case "$deb_arch" in
	amd64) efi_arch=x64 ;;
	arm64) efi_arch=aa64 ;;
	*) die "no signed systemd-boot is known for architecture '${deb_arch}'" ;;
	esac
	binary="${TUNAOS_SYSROOT:-}/usr/lib/systemd/boot/efi/systemd-boot${efi_arch}.efi.signed"
fi

echo "== signed systemd-boot: ${binary} =="
[[ -s "$binary" ]] ||
	die "${binary} is missing. Install systemd-boot-efi-<arch>-signed."
command -v sbverify >/dev/null 2>&1 ||
	die "sbverify is missing. Install sbsigntool before this check."
[[ -s "$CA_PEM" ]] || die "the pinned certificate ${CA_PEM} is missing"

pem_sha256="$(sed '/^-----/d' "$CA_PEM" | base64 -d | sha256sum | cut -d' ' -f1)"
[[ "$pem_sha256" == "$CA_DER_SHA256" ]] ||
	die "${CA_PEM} has sha256 ${pem_sha256}, not the pinned ${CA_DER_SHA256}"

listing="$(sbverify --list "$binary" 2>&1 || true)"
echo "$listing"
grep -q '^signature 1$' <<<"$listing" ||
	die "${binary} has no signature (sbverify --list shows none)"

sbverify --cert "$CA_PEM" "$binary" ||
	die "the signature of ${binary} does not chain to the Debian Secure Boot CA"

echo "== signed systemd-boot: OK =="
