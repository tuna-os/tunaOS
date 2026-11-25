#!/usr/bin/env bash
# CI signing step for tunaos-key cells (tunaOS#4955). Signing runs in CI only.
#
# Usage:
#   ci-sign.sh efi IN.efi OUT.efi      sign one EFI binary (systemd-boot, UKI)
#   ci-sign.sh auth ESL_DIR OUT_DIR    sign PK.esl, KEK.esl, db.esl into
#                                      PK.auth, KEK.auth, db.auth
#   add --dry-run to print each command and sign nothing
#
# Inputs, from the organisation secrets of the same names:
#   TUNAOS_SB_CERT     PEM certificate. Must equal the committed public
#                      certificate (certs/tunaos-sb.crt), or the step stops.
#   TUNAOS_SB_KEY      PEM private key, or
#   TUNAOS_SB_KEY_URI  a pkcs11: URI for an HSM or KMS key (sbsign --engine
#                      pkcs11). When set, TUNAOS_SB_KEY is not read.
#
# The key never reaches stdout, a log, the work tree or an artifact. It lives
# in a mode-0600 file under a private directory on tmpfs for the length of
# this process, and the EXIT trap removes it. `set -x` is refused.
#
# ESL_DIR comes from `secureboot.py build-esl`, which reads public
# certificates only. PK.auth and KEK.auth carry the signature of the PK;
# db.auth too, because the tunaOS certificate is also the KEK.
set -euo pipefail

case "$-" in *x*)
	echo "ci-sign: refuse to run under set -x: a trace prints the key" >&2
	exit 1
	;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_CERT="${TUNAOS_SB_EXPECTED_CERT:-${HERE}/certs/tunaos-sb.crt}"
ATTR=NON_VOLATILE,RUNTIME_ACCESS,BOOTSERVICE_ACCESS,TIME_BASED_AUTHENTICATED_WRITE_ACCESS

usage() {
	echo "usage: ci-sign.sh efi IN OUT [--dry-run] | ci-sign.sh auth ESL_DIR OUT_DIR [--dry-run]" >&2
	exit 2
}

MODE="${1:-}"
SRC="${2:-}"
DST="${3:-}"
DRY_RUN="${4:-}"
[[ -n "${MODE}" && -n "${SRC}" && -n "${DST}" ]] || usage
[[ -z "${DRY_RUN}" || "${DRY_RUN}" = "--dry-run" ]] || usage

if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	case "${MODE}" in
	efi) echo "ci-sign: sbsign --key <TUNAOS_SB_KEY> --cert <TUNAOS_SB_CERT> --output ${DST} ${SRC}" ;;
	auth)
		for name in PK KEK db; do
			echo "ci-sign: sbvarsign --attr ${ATTR} --key <TUNAOS_SB_KEY> --cert <TUNAOS_SB_CERT> --output ${DST}/${name}.auth ${name} ${SRC}/${name}.esl"
		done
		;;
	*) usage ;;
	esac
	exit 0
fi

[[ -n "${TUNAOS_SB_CERT:-}" ]] || {
	echo "ci-sign: TUNAOS_SB_CERT is not set" >&2
	exit 1
}
[[ -n "${TUNAOS_SB_KEY:-}" || -n "${TUNAOS_SB_KEY_URI:-}" ]] || {
	echo "ci-sign: set TUNAOS_SB_KEY or TUNAOS_SB_KEY_URI" >&2
	exit 1
}

fingerprint() {
	openssl x509 -outform DER | sha256sum | cut -d' ' -f1
}

# tmpfs only: the key must not reach a disk.
SECRETS="$(umask 077 && mktemp -d "${XDG_RUNTIME_DIR:-/dev/shm}/tunaos-sb.XXXXXX")"
trap 'rm -rf -- "${SECRETS}"' EXIT
(umask 077 && printf '%s\n' "${TUNAOS_SB_CERT}" >"${SECRETS}/cert.pem")

# A signature from another certificate verifies nowhere: stop before signing.
if [[ "$(fingerprint <"${SECRETS}/cert.pem")" != "$(fingerprint <"${EXPECTED_CERT}")" ]]; then
	echo "ci-sign: TUNAOS_SB_CERT differs from ${EXPECTED_CERT}" >&2
	exit 1
fi

KEY_ARGS=()
if [[ -n "${TUNAOS_SB_KEY_URI:-}" ]]; then
	KEY_ARGS=(--engine pkcs11 --key "${TUNAOS_SB_KEY_URI}")
else
	(umask 077 && printf '%s\n' "${TUNAOS_SB_KEY}" >"${SECRETS}/key.pem")
	if [[ "$(openssl pkey -in "${SECRETS}/key.pem" -pubout 2>/dev/null)" != "$(openssl x509 -in "${SECRETS}/cert.pem" -pubkey -noout)" ]]; then
		echo "ci-sign: TUNAOS_SB_KEY does not match TUNAOS_SB_CERT" >&2
		exit 1
	fi
	KEY_ARGS=(--key "${SECRETS}/key.pem")
fi

case "${MODE}" in
efi)
	sbsign "${KEY_ARGS[@]}" --cert "${SECRETS}/cert.pem" --output "${DST}" "${SRC}" >/dev/null 2>&1 || {
		echo "ci-sign: sbsign failed for ${SRC}" >&2
		exit 1
	}
	sbverify --cert "${SECRETS}/cert.pem" "${DST}" >/dev/null
	echo "ci-sign: signed ${DST}"
	;;
auth)
	mkdir -p "${DST}"
	for name in PK KEK db; do
		[[ -s "${SRC}/${name}.esl" ]] || {
			echo "ci-sign: missing ${SRC}/${name}.esl (run secureboot.py build-esl)" >&2
			exit 1
		}
		sbvarsign --attr "${ATTR}" "${KEY_ARGS[@]}" --cert "${SECRETS}/cert.pem" \
			--output "${DST}/${name}.auth" "${name}" "${SRC}/${name}.esl" >/dev/null 2>&1 || {
			echo "ci-sign: sbvarsign failed for ${name}" >&2
			exit 1
		}
		echo "ci-sign: signed ${DST}/${name}.auth"
	done
	;;
*) usage ;;
esac
