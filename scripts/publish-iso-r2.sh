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

is_retained() {
	[[ "$(python3 "$policy" --config-json "$config_json" \
		object-protected --object "$1")" == true ]]
}

copy_unless_retained() {
	local source=$1 object=$2
	if is_retained "$object"; then
		echo "::notice::retained R2 object is immutable; skipping ${object}"
		return
	fi
	rclone copyto --log-level INFO --checksum --s3-no-check-bucket \
		"$source" "${destination}/${object}"
}

versioned=$(basename "$iso")
copy_unless_retained "$iso" "$versioned"
copy_unless_retained "$checksum" "${versioned}.sha256"
copy_unless_retained "$bundle" "${versioned}.sigstore.json"

copy_unless_retained "$iso" "$latest"
latest_checksum="${latest}.sha256"
digest=$(sha256sum "$iso" | awk '{print $1}')
printf '%s  %s\n' "$digest" "$latest" >"$latest_checksum"
copy_unless_retained "$latest_checksum" "$latest_checksum"
copy_unless_retained "$bundle" "${latest}.sigstore.json"

echo "==> Published unprotected destinations for ${versioned} and ${latest}"
