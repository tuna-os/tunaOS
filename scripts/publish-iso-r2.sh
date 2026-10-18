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

publication_name() {
	local requested=$1 retained_status=0
	is_retained "$requested" || retained_status=$?
	case "$retained_status" in
	0)
		printf '%s-sha256-%s.iso\n' "${requested%.iso}" "$digest_suffix"
		;;
	1) printf '%s\n' "$requested" ;;
	*) return "$retained_status" ;;
	esac
}

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

publish_iso_as() {
	local object=$1
	local checksum_file="${tmpdir}/${object##*/}.sha256"
	printf '%s  %s\n' "$digest" "$object" >"$checksum_file"
	copy_unless_retained "$iso" "$object"
	copy_unless_retained "$checksum_file" "${object}.sha256"
	copy_unless_retained "$bundle" "${object}.sigstore.json"
}

versioned=$(basename "$iso")
versioned_publication=$(publication_name "$versioned")
latest_publication=$(publication_name "$latest")
publish_iso_as "$versioned_publication"
publish_iso_as "$latest_publication"

# A stable, small resolver keeps rollback publication discoverable when the
# historical -latest object itself is immutable. It points only at the signed,
# checksum-addressed artifact set above.
resolver="${latest%.iso}.json"
resolver_file="${tmpdir}/${resolver##*/}"
printf '{"schema":"TunaOSIsoResolution/v1","iso":"%s","sha256":"%s.sha256","sigstore":"%s.sigstore.json","digest":"sha256:%s"}\n' \
	"$latest_publication" "$latest_publication" "$latest_publication" "$digest" \
	>"$resolver_file"
copy_unless_retained "$resolver_file" "$resolver"

echo "==> Published ${versioned_publication}; ${resolver} resolves current download to ${latest_publication}"
