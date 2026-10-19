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
	if [[ "$object" == *-snapshot-*.iso ]]; then
		# A resolver may only point at a newly published snapshot. Reusing an
		# existing object lets a concurrent prune delete that old snapshot
		# between resolver collection and deletion, including its sidecars.
		for candidate in "$object" "${object}.sha256" "${object}.sigstore.json"; do
			local existing
			if ! existing="$(rclone lsf --s3-no-check-bucket --files-only \
				--include "/${candidate}" "${destination}/")"; then
				echo "ERROR: could not check whether snapshot object exists: ${candidate}" >&2
				return 1
			fi
			if [[ -n "$existing" ]]; then
				echo "ERROR: refusing to reactivate existing snapshot object: ${candidate}" >&2
				return 1
			fi
		done
	fi
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
# A resolver is needed only when policy freezes the stable alias. Its
# publication_name is already unique to this run, so it is both the resolver
# target and the second full ISO copy. Routine publication keeps the legacy
# two-copy layout (versioned + latest) and creates no resolver.
publish_iso_as "$versioned_publication"
if [[ "$latest_publication" == "$latest" ]]; then
	publish_iso_as "$latest_publication"
	echo "==> Published ${versioned_publication} and mutable ${latest_publication}; no frozen alias resolver required"
	exit 0
fi

publish_iso_as "$latest_publication"

# Publish the stable resolver only after its immutable ISO, checksum, and
# signature bundle. The retained legacy alias remains frozen for clients that
# do not yet understand resolvers.
resolver="${latest%.iso}.json"
resolver_file="${tmpdir}/${resolver##*/}"
printf '{"schema":"TunaOSIsoResolution/v1","iso":"%s","sha256":"%s.sha256","sigstore":"%s.sigstore.json","checksum_subject":"%s","digest":"sha256:%s"}\n' \
	"$latest_publication" "$latest_publication" "$latest_publication" \
	"$(basename "$iso")" "$digest" >"$resolver_file"
copy_unless_retained "$resolver_file" "$resolver"

echo "==> Published ${versioned_publication}; ${resolver} resolves current download to ${latest_publication}"
