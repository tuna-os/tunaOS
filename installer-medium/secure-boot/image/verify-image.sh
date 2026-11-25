#!/usr/bin/env bash
# Check that an image keeps the tunaos-key contract (tunaOS#4955). No key.
#
# Usage: verify-image.sh IMAGE [--reject-cert PEM]...
#
# IMAGE is a name in the local container storage. The checks:
#   - the plain systemd-boot has no signature;
#   - the .signed systemd-boot has exactly one signature, and it verifies
#     against the committed tunaOS certificate;
#   - each /usr/lib/modules/*/vmlinuz verifies against that certificate;
#   - with --reject-cert, no boot file verifies against that certificate
#     (Brussels: the public test certificate of gnome-build-meta);
#   - the certificate in the image is the committed one, and `mode` says
#     tunaos-key;
#   - `secureboot.py stage` accepts the files: a Microsoft UEFI CA signed
#     shim, MokManager verifies against the certificate inside shim, and the
#     key bundle holds the tunaOS and Microsoft certificates.
# The last check stages the files into a scratch ESP, the same way
# stage-medium.sh does for the medium, so an image that passes here gives a
# medium that the stage step accepts.
#
# SB_CERT, SB_ARCH and PODMAN mean the same as in sign-image.sh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SB="$(dirname "${HERE}")"
IMAGE="${1:?usage: verify-image.sh IMAGE [--reject-cert PEM]...}"
shift
REJECT=()
while [[ $# -gt 0 ]]; do
	[[ "$1" = "--reject-cert" && -s "${2:-}" ]] || {
		echo "usage: verify-image.sh IMAGE [--reject-cert PEM]..." >&2
		exit 2
	}
	REJECT+=("$2")
	shift 2
done
ARCH="${SB_ARCH:-x64}"
CERT="${SB_CERT:-${SB}/certs/tunaos-sb.crt}"
PODMAN="${PODMAN:-podman}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/verify-image.XXXXXX")"
CTR=""
cleanup() {
	[[ -z "${CTR}" ]] || "${PODMAN}" rm -f "${CTR}" >/dev/null 2>&1 || true
	rm -rf -- "${WORK}"
}
trap cleanup EXIT
fail() {
	echo "verify-image: $*" >&2
	exit 1
}

LOADER="usr/lib/systemd/boot/efi/systemd-boot${ARCH}.efi"
SHARE="usr/lib/tunaos/secure-boot"
mkdir -p "${WORK}/in" "${WORK}/esp/EFI/Linux"
CTR="$("${PODMAN}" create "${IMAGE}" /bin/true)"
"${PODMAN}" export "${CTR}" | tar -x -C "${WORK}/in" --wildcards \
	"${LOADER}" "${LOADER}.signed" 'usr/lib/modules/*/vmlinuz' "${SHARE}" usr/bin/tuna-secure-boot ||
	fail "${IMAGE} lacks a file of the tunaos-key contract"
cd "${WORK}/in"

signatures() {
	sbverify --list "$1" 2>/dev/null | grep -c '^signature [0-9]' || true
}

[[ "$(signatures "${LOADER}")" = "0" ]] || fail "/${LOADER} has a signature; only the .signed file may have one"
[[ "$(signatures "${LOADER}.signed")" = "1" ]] || fail "/${LOADER}.signed must have exactly one signature"
mapfile -t KERNELS < <(find usr/lib/modules -mindepth 2 -maxdepth 2 -name vmlinuz | sort)
[[ ${#KERNELS[@]} -gt 0 ]] || fail "no kernel in /usr/lib/modules"
n=0
for file in "${LOADER}.signed" "${KERNELS[@]}"; do
	sbverify --cert "${CERT}" "${file}" >/dev/null 2>&1 || fail "/${file} does not verify against the tunaOS certificate"
	for other in "${REJECT[@]}"; do
		if sbverify --cert "${other}" "${file}" >/dev/null 2>&1; then
			fail "/${file} verifies against ${other}, which must not sign a published image"
		fi
	done
	# The stage step checks each PE file on the ESP against the certificate.
	n=$((n + 1))
	[[ "${file}" = "${LOADER}.signed" ]] || cp "${file}" "${WORK}/esp/EFI/Linux/kernel-${n}.efi"
done

[[ "$(cat "${SHARE}/mode")" = "tunaos-key" ]] || fail "/${SHARE}/mode is not tunaos-key"
[[ -x usr/bin/tuna-secure-boot ]] || fail "/usr/bin/tuna-secure-boot is not executable"
want="$(openssl x509 -in "${CERT}" -outform DER | sha256sum | cut -d' ' -f1)"
have="$(sha256sum "${SHARE}/tunaos-secure-boot.cer" | cut -d' ' -f1)"
[[ "${want}" = "${have}" ]] || fail "/${SHARE}/tunaos-secure-boot.cer is not the committed certificate"
pin="$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["shim"][sys.argv[2]]["sha256"])' "${SHARE}/provenance.toml" "${ARCH}")"
ours="$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["shim"][sys.argv[2]]["sha256"])' "${HERE}/shim.toml" "${ARCH}")"
[[ "${pin}" = "${ours}" ]] || fail "/${SHARE}/provenance.toml names another shim than shim.toml"

python3 "${SB}/secureboot.py" stage --esp "${WORK}/esp" --arch "${ARCH}" --cert "${CERT}" \
	--shim-dir "${SHARE}" --loader "${LOADER}.signed" --auth-dir "${SHARE}/keys/auto" >/dev/null ||
	fail "secureboot.py stage refuses the files of ${IMAGE}"
echo "verify-image: ${IMAGE} keeps the tunaos-key contract (${#KERNELS[@]} kernel(s))"
