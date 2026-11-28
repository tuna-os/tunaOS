#!/usr/bin/env bash
# The initramfs must carry the TPM2 token plugin of cryptsetup, or a LUKS root
# enrolled with the TPM is never opened at boot (tunaOS#5141).
# Usage: verify-initramfs-tpm2.sh INITRAMFS
set -euo pipefail

img="${1:?initramfs path}"
if ! lsinitrd "${img}" | grep -q 'libcryptsetup-token-systemd-tpm2\.so'; then
	echo "ERROR: ${img} has no libcryptsetup-token-systemd-tpm2.so: the installed system could not unlock a TPM-enrolled LUKS root (tunaOS#5141)" >&2
	exit 1
fi
