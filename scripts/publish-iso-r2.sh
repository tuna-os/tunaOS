#!/usr/bin/env bash
# Publish one signed ISO without overwriting immutable retained R2 objects.

set -euo pipefail

if [[ $# -ne 4 ]]; then
	echo "usage: $0 ISO LATEST_NAME CONFIG_JSON R2_DEST" >&2
	exit 2
fi

iso=$1
latest=$2
config_json=$3
destination=${4%/}
policy="$(dirname "$0")/iso-delivery-policy.py"
checksum="${iso}.sha256"
bundle="${iso}.sigstore.json"

for source in "$iso" "$checksum" "$bundle"; do
	[[ -f "$source" ]] || {
		echo "ERROR: missing signed ISO artifact: $source" >&2
		exit 1
	}
done

if ! python3 "$policy" --config-json "$config_json" validate >/dev/null; then
	echo "ERROR: refusing R2 publication because the ISO delivery policy is invalid" >&2
	exit 1
fi

is_retained() {
	local result
	if ! result="$(python3 "$policy" --config-json "$config_json" \
		object-protected --object "$1")"; then
		echo "ERROR: could not evaluate retention policy for $1" >&2
		return 2
	fi
	case "$result" in
	true) return 0 ;;
	false) return 1 ;;
	*)
		echo "ERROR: retention policy returned an invalid verdict for $1: $result" >&2
		return 2
		;;
	esac
}

copy_unless_retained() {
	local source=$1 object=$2 retained_status=0
	is_retained "$object" || retained_status=$?
	case "$retained_status" in
	0)
		echo "::notice::retained R2 object is immutable; skipping ${object}"
		return
		;;
	1) ;;
	*) return "$retained_status" ;;
	esac
	rclone copyto --log-level INFO --checksum --s3-no-check-bucket \
		"$source" "${destination}/${object}"
}

digest=$(sha256sum "$iso" | awk '{print $1}')
digest_suffix=${digest:0:16}
publication_id="${TUNAOS_PUBLICATION_ID:-}"
if [[ -z "$publication_id" && -n "${GITHUB_RUN_ID:-}" ]]; then
	publication_id="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
fi
if [[ -z "$publication_id" ]]; then
	publication_id="$(date -u +%Y%m%dT%H%M%S%N)-${BASHPID}"
fi
if [[ ! "$publication_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
	echo "ERROR: publication id contains unsafe object-name characters: ${publication_id}" >&2
	exit 1
fi

publication_name() {
	local requested=$1 retained_status=0
	is_retained "$requested" || retained_status=$?
	case "$retained_status" in
	0)
		local snapshot="${requested%.iso}"
		snapshot="${snapshot/-latest/-snapshot}"
		printf '%s-run-%s-sha256-%s.iso\n' "$snapshot" "$publication_id" "$digest_suffix"
		;;
	1) printf '%s\n' "$requested" ;;
	*) return "$retained_status" ;;
	esac
}

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

publish_iso_as() {
	local object=$1
	copy_unless_retained "$iso" "$object"
	# Keep the exact checksum bytes that cosign signed. The checksum subject is
	# the build artifact's original basename; resolver-aware consumers verify
	# its digest field against the downloaded publication name.
	copy_unless_retained "$checksum" "${object}.sha256"
	copy_unless_retained "$bundle" "${object}.sigstore.json"
}

versioned=$(basename "$iso")
versioned_publication=$(publication_name "$versioned")
latest_publication=$(publication_name "$latest")
# Every publication gets a new immutable resolver target, even when it
# republishes identical bytes. A prune that captured an older resolver set
# can therefore never delete a concurrently reactivated old snapshot: the
# new target has a new key and a fresh mtime before the resolver switches.
resolver_base="${latest%.iso}"
resolver_base="${resolver_base/-latest/-snapshot}"
resolver_publication="${resolver_base}-run-${publication_id}-sha256-${digest_suffix}.iso"
publish_iso_as "$versioned_publication"
publish_iso_as "$resolver_publication"
if [[ "$latest_publication" != "$resolver_publication" ]]; then
	publish_iso_as "$latest_publication"
fi

# Publish the stable resolver only after its immutable ISO, checksum, and
# signature bundle. The legacy alias above remains for non-resolver clients.
resolver="${latest%.iso}.json"
resolver_file="${tmpdir}/${resolver##*/}"
printf '{"schema":"TunaOSIsoResolution/v1","iso":"%s","sha256":"%s.sha256","sigstore":"%s.sigstore.json","checksum_subject":"%s","digest":"sha256:%s"}\n' \
	"$resolver_publication" "$resolver_publication" "$resolver_publication" \
	"$(basename "$iso")" "$digest" >"$resolver_file"
copy_unless_retained "$resolver_file" "$resolver"

echo "==> Published ${versioned_publication}; ${resolver} resolves current download to ${resolver_publication}"
