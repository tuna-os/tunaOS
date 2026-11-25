#!/usr/bin/env bash
# Add the tunaos-key Secure Boot layer to a built image (tunaOS#4955).
#
# Usage (CI, publish jobs only):
#   sign-image.sh SRC_IMAGE DST_IMAGE
#
# SRC_IMAGE and DST_IMAGE are names in the local container storage; they can
# be the same name. The script changes nothing else: no push, no registry.
#
# For a BuildStream image (tuna-os/tromso, tuna-os/brussels) the key must not
# enter the build: BuildStream keeps each source in its cache, and CI
# publishes that cache. So the signature is a layer that the publish job adds
# after the build and before the push. The layer holds what
# docs/SECURE-BOOT.md calls "What the image must ship":
#
#   /usr/lib/systemd/boot/efi/systemd-boot<arch>.efi          no signature
#   /usr/lib/systemd/boot/efi/systemd-boot<arch>.efi.signed   tunaOS signature
#   /usr/lib/modules/<version>/vmlinuz                        tunaOS signature
#   /usr/lib/tunaos/secure-boot/{shim,mm}<arch>.efi           Fedora shim, by pin
#   /usr/lib/tunaos/secure-boot/tunaos-secure-boot.cer        public certificate
#   /usr/lib/tunaos/secure-boot/keys/auto/{PK,KEK,db}.auth    key bundle
#   /usr/lib/tunaos/secure-boot/mode                          "tunaos-key"
#   /usr/lib/tunaos/secure-boot/provenance.toml               the shim pin
#   /usr/bin/tuna-secure-boot                                 the helper
#
# A signature that the build left on systemd-boot or on a kernel is removed
# first. gnome-build-meta signs systemd-boot with a public test key; that
# signature must not ship.
#
# Inputs: TUNAOS_SB_KEY (or TUNAOS_SB_KEY_URI) and TUNAOS_SB_CERT, read by
# ci-sign.sh only. This script never reads the key and passes no secret to a
# container. Options for tests and offline runs:
#   SB_SHIM_RPM    a local copy of the pinned RPM (the sha256 is still checked)
#   SB_CERT        the signing certificate, PEM (default: certs/tunaos-sb.crt);
#                  a test with a throwaway key sets it, with
#                  TUNAOS_SB_EXPECTED_CERT for ci-sign.sh
#   SB_ARCH        x64 (default)
#   PODMAN         the podman command (default: podman)
set -euo pipefail

case "$-" in *x*)
	echo "sign-image: refuse to run under set -x" >&2
	exit 1
	;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SB="$(dirname "${HERE}")"
USAGE="usage: sign-image.sh SRC_IMAGE DST_IMAGE"
SRC="${1:?${USAGE}}"
DST="${2:?${USAGE}}"
ARCH="${SB_ARCH:-x64}"
CERT="${SB_CERT:-${SB}/certs/tunaos-sb.crt}"
PODMAN="${PODMAN:-podman}"
[[ "${ARCH}" = "x64" ]] || {
	echo "sign-image: only x64 has a shim pin" >&2
	exit 1
}
for tool in sbsign sbverify sbattach sbvarsign openssl python3 curl "${PODMAN}"; do
	command -v "${tool}" >/dev/null || {
		echo "sign-image: ${tool} is missing" >&2
		exit 1
	}
done
if [[ -n "${SB_CERT:-}" ]]; then
	export TUNAOS_SB_EXPECTED_CERT="${TUNAOS_SB_EXPECTED_CERT:-${SB_CERT}}"
fi

# The layer copies its directories over /usr, /usr/lib and /usr/bin of the
# image. Mode 0755 and the build time are right for them; a tighter umask of
# the caller would make /usr unreadable in the published image.
umask 022
WORK="$(mktemp -d "${TMPDIR:-/tmp}/sign-image.XXXXXX")"
chmod 0755 "${WORK}"
CTR=""
cleanup() {
	[[ -z "${CTR}" ]] || "${PODMAN}" rm -f "${CTR}" >/dev/null 2>&1 || true
	[[ -z "${MNT:-}" ]] || "${PODMAN}" image umount "${SRC}" >/dev/null 2>&1 || true
	rm -rf -- "${WORK}"
}
trap cleanup EXIT

LOADER="usr/lib/systemd/boot/efi/systemd-boot${ARCH}.efi"
mkdir -p "${WORK}/in" "${WORK}/tree/usr/lib/tunaos/secure-boot/keys/auto" "${WORK}/tree/usr/bin"

# 1. Take the loader and each kernel out of the image. The image never runs.
#    A mount is fast and needs root (CI) or `podman unshare`; an export of
#    the whole image works everywhere and is slow.
if MNT="$("${PODMAN}" image mount "${SRC}" 2>/dev/null)" && [[ -d "${MNT}/usr" ]]; then
	# A missing file is reported by the checks below, with a clear message.
	(cd "${MNT}" && tar -c "${LOADER}" usr/lib/modules/*/vmlinuz 2>/dev/null) | tar -x -C "${WORK}/in" || true
	"${PODMAN}" image umount "${SRC}" >/dev/null
else
	CTR="$("${PODMAN}" create "${SRC}" /bin/true)"
	"${PODMAN}" export "${CTR}" | tar -x -C "${WORK}/in" --wildcards "${LOADER}" 'usr/lib/modules/*/vmlinuz'
fi
[[ -s "${WORK}/in/${LOADER}" ]] || {
	echo "sign-image: ${SRC} has no /${LOADER}" >&2
	exit 1
}
mapfile -t KERNELS < <(cd "${WORK}/in" && find usr/lib/modules -mindepth 2 -maxdepth 2 -name vmlinuz | sort)
[[ ${#KERNELS[@]} -gt 0 ]] || {
	echo "sign-image: ${SRC} has no /usr/lib/modules/*/vmlinuz" >&2
	exit 1
}

# 2. Remove each signature that the build made.
strip_signatures() {
	local file="$1" left=8
	while sbverify --list "${file}" 2>/dev/null | grep -q '^signature [0-9]'; do
		sbattach --remove "${file}" >/dev/null 2>&1
		left=$((left - 1))
		[[ ${left} -gt 0 ]] || {
			echo "sign-image: cannot remove the signatures of ${file}" >&2
			exit 1
		}
	done
}

# 3. Sign. ci-sign.sh checks the key against the certificate, signs, and
#    verifies the result. The plain loader stays in the image with no
#    signature; `bootctl install` and bootc prefer the .signed file.
install -D -m 0644 "${WORK}/in/${LOADER}" "${WORK}/tree/${LOADER}"
strip_signatures "${WORK}/tree/${LOADER}"
"${SB}/ci-sign.sh" efi "${WORK}/tree/${LOADER}" "${WORK}/tree/${LOADER}.signed"
for kernel in "${KERNELS[@]}"; do
	install -D -m 0644 "${WORK}/in/${kernel}" "${WORK}/unsigned/${kernel}"
	strip_signatures "${WORK}/unsigned/${kernel}"
	mkdir -p "$(dirname "${WORK}/tree/${kernel}")"
	"${SB}/ci-sign.sh" efi "${WORK}/unsigned/${kernel}" "${WORK}/tree/${kernel}"
done

# 4. The key bundle for systemd-boot, from public certificates, signed by CI.
python3 "${SB}/secureboot.py" build-esl --cert "${CERT}" --out "${WORK}/esl"
"${SB}/ci-sign.sh" auth "${WORK}/esl" "${WORK}/tree/usr/lib/tunaos/secure-boot/keys/auto"

# 5. The Fedora shim and MokManager, by pin.
mapfile -t PIN < <(
	python3 - "${HERE}/shim.toml" "${ARCH}" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    pin = tomllib.load(handle)["shim"][sys.argv[2]]
for key in ("url", "sha256", "shim", "mok_manager"):
    print(pin[key])
PY
)
RPM="${SB_SHIM_RPM:-}"
if [[ -z "${RPM}" ]]; then
	RPM="${WORK}/shim.rpm"
	curl --fail --silent --show-error --location --retry 3 --output "${RPM}" "${PIN[0]}"
fi
[[ "$(sha256sum "${RPM}" | cut -d' ' -f1)" = "${PIN[1]}" ]] || {
	echo "sign-image: the shim RPM differs from the sha256 in shim.toml" >&2
	exit 1
}
mkdir -p "${WORK}/shim"
if command -v bsdtar >/dev/null; then
	bsdtar -xf "${RPM}" -C "${WORK}/shim" "./${PIN[2]}" "./${PIN[3]}"
else
	(cd "${WORK}/shim" && rpm2cpio "${RPM}" | cpio -idm --quiet "./${PIN[2]}" "./${PIN[3]}")
fi
SHARE="${WORK}/tree/usr/lib/tunaos/secure-boot"
install -m 0644 "${WORK}/shim/${PIN[2]}" "${SHARE}/shim${ARCH}.efi"
install -m 0644 "${WORK}/shim/${PIN[3]}" "${SHARE}/mm${ARCH}.efi"
install -m 0644 "${HERE}/shim.toml" "${SHARE}/provenance.toml"

# 6. The certificate, the mode and the helper.
openssl x509 -in "${CERT}" -outform DER -out "${SHARE}/tunaos-secure-boot.cer"
printf 'tunaos-key\n' >"${SHARE}/mode"
install -m 0755 "${SB}/tuna-secure-boot" "${WORK}/tree/usr/bin/tuna-secure-boot"

# 7. One layer on top of the image. Labels and the config stay as they are.
printf 'FROM %s\nCOPY tree/ /\n' "${SRC}" >"${WORK}/Containerfile"
"${PODMAN}" build --pull=never --quiet -f "${WORK}/Containerfile" -t "${DST}" "${WORK}" >/dev/null
echo "sign-image: ${DST} has the tunaos-key layer (${#KERNELS[@]} kernel(s))"
