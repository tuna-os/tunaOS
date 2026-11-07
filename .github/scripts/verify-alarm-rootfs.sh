#!/usr/bin/env bash
# verify-alarm-rootfs.sh ROOTFS SIG KEYFILE FINGERPRINT
#
# Verify the Arch Linux ARM rootfs against its detached GPG signature, failing
# closed. Trust comes from FINGERPRINT (the ALARM build key, pinned in the
# calling workflow) and nothing the mirror serves:
#
#   * KEYFILE must hold exactly one primary key and it must be FINGERPRINT;
#   * only that file is imported, into a throwaway GNUPGHOME;
#   * gpg's --status-fd output must carry exactly one VALIDSIG whose primary
#     key fingerprint is FINGERPRINT, and no BADSIG/ERRSIG/EXPKEYSIG/
#     EXPKEYREVOKED/REVKEYSIG/NO_PUBKEY line.
#
# The .md5 sidecar is deliberately not used: it comes from the same mirror as
# the tarball, so it proves nothing about who built it (tunaOS#3394).
set -euo pipefail

if [[ $# -ne 4 ]]; then
	echo "usage: verify-alarm-rootfs.sh ROOTFS SIG KEYFILE FINGERPRINT" >&2
	exit 2
fi
rootfs="$1" sig="$2" keyfile="$3" fingerprint="$4"

fail() {
	echo "::error::ALARM rootfs verification failed: $*" >&2
	exit 1
}

[[ "$fingerprint" =~ ^[0-9A-F]{40}$ ]] || fail "pinned fingerprint is not 40 uppercase hex characters"
for f in "$rootfs" "$sig" "$keyfile"; do
	[[ -s "$f" ]] || fail "missing or empty input: $f"
done

GNUPGHOME="$(mktemp -d)"
export GNUPGHOME
trap 'rm -rf "$GNUPGHOME"' EXIT
chmod 700 "$GNUPGHOME"

# `pub` is followed by that key's own `fpr` record; a `sub` fpr follows `sub`.
mapfile -t primaries < <(gpg --batch --show-keys --with-colons "$keyfile" |
	awk -F: '/^pub:/ {want = 1; next} /^sub:/ {want = 0} /^fpr:/ && want {print $10; want = 0}')
[[ "${#primaries[@]}" -eq 1 && "${primaries[0]}" == "$fingerprint" ]] ||
	fail "key file does not contain exactly the pinned key ${fingerprint}"

gpg --batch --quiet --import "$keyfile" 2>/dev/null

status="$(gpg --batch --status-fd 1 --verify "$sig" "$rootfs" 2>/dev/null)" ||
	fail "gpg --verify rejected the signature"

if grep -Eq '^\[GNUPG:\] (BADSIG|ERRSIG|EXPSIG|EXPKEYSIG|REVKEYSIG|NO_PUBKEY) ' <<<"$status"; then
	fail "gpg reported a bad, expired, revoked or unknown-key signature"
fi

# VALIDSIG <fpr> <date> <ts> <expire> <ver> <rsvd> <pk-algo> <hash> <class> <primary-fpr>
mapfile -t valid < <(awk '$1 == "[GNUPG:]" && $2 == "VALIDSIG" {print $12}' <<<"$status")
[[ "${#valid[@]}" -eq 1 && "${valid[0]}" == "$fingerprint" ]] ||
	fail "no single VALIDSIG from primary key ${fingerprint}"

echo "ALARM rootfs signature OK: ${rootfs} signed by ${fingerprint}"
