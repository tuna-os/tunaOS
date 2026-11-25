#!/usr/bin/env bash
# Sign what a tunaos-key medium boots, in CI, on a mounted medium (tunaOS#4955).
#
# Usage (CI, root): installer-medium/secure-boot/sign-medium.sh ESP OUT [--dry-run]
#
# Signs each boot binary on ESP that lacks the tunaOS signature (systemd-boot,
# each kernel or UKI that an entry names) in place, and writes into OUT:
#   OUT/systemd-boot<arch>.efi.signed   the loader that shim starts
#   OUT/auth/{PK,KEK,db}.auth           the key bundle for systemd-boot
# stage-medium.sh takes both through MEDIUM_SB_LOADER and MEDIUM_SB_AUTH_DIR.
#
# The key comes from TUNAOS_SB_KEY (or TUNAOS_SB_KEY_URI) and TUNAOS_SB_CERT,
# which only a trusted workflow event has. ci-sign.sh is the only code that
# reads them.
#
# Exit status: 0 signed; 3 no key in the environment (the caller decides: a
# pull request builds an unsigned medium and must not publish it); 1 an error.
# With --dry-run, print each step and sign nothing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USAGE="usage: sign-medium.sh ESP OUT [--dry-run]"
ESP="${1:?${USAGE}}"
OUT="${2:?${USAGE}}"
DRY_RUN="${3:-}"
ARCH="${MEDIUM_SB_ARCH:-x64}"
TOOL=(python3 "${HERE}/secureboot.py")
LOADER="EFI/systemd/systemd-boot${ARCH}.efi"

if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "sign-medium: ci-sign.sh efi <each boot binary on ${ESP} with no tunaOS signature> (in place)"
	echo "sign-medium: ci-sign.sh efi ${ESP}/${LOADER} ${OUT}/systemd-boot${ARCH}.efi.signed"
	echo "sign-medium: secureboot.py build-esl --out ${OUT}/esl; ci-sign.sh auth ${OUT}/esl ${OUT}/auth"
	exit 0
fi

if [[ -z "${TUNAOS_SB_CERT:-}" || (-z "${TUNAOS_SB_KEY:-}" && -z "${TUNAOS_SB_KEY_URI:-}") ]]; then
	echo "sign-medium: no TUNAOS_SB_KEY and TUNAOS_SB_CERT on this event: nothing signed" >&2
	exit 3
fi

[[ -f "${ESP}/${LOADER}" ]] || {
	echo "sign-medium: ${LOADER} is not on the ESP: a tunaos-key cell boots systemd-boot" >&2
	exit 1
}
mkdir -p "${OUT}"
# A test names its own certificate directory; CI reads the committed one.
[[ -z "${MEDIUM_SB_CERTS_DIR:-}" ]] || TOOL+=(--certs-dir "${MEDIUM_SB_CERTS_DIR}")
unsigned="$("${TOOL[@]}" unsigned --esp "${ESP}")"
while IFS= read -r path; do
	[[ -n "${path}" ]] || continue
	"${HERE}/ci-sign.sh" efi "${path}" "${path}.tunaos-signed"
	mv -f -- "${path}.tunaos-signed" "${path}"
done <<<"${unsigned}"
cp -f -- "${ESP}/${LOADER}" "${OUT}/systemd-boot${ARCH}.efi.signed"
"${TOOL[@]}" build-esl --out "${OUT}/esl"
"${HERE}/ci-sign.sh" auth "${OUT}/esl" "${OUT}/auth"
left="$("${TOOL[@]}" unsigned --esp "${ESP}")"
[[ -z "${left}" ]] || {
	echo "sign-medium: still unsigned after the sign step:" >&2
	echo "${left}" >&2
	exit 1
}
echo "sign-medium: signed the boot binaries on ${ESP}; loader and key bundle in ${OUT}"
