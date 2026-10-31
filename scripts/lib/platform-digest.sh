#!/usr/bin/env bash
# Resolve the manifest digest for the platform stored in the local container
# image store. This is deliberately not a registry lookup: the caller may have
# pulled or built a different image than the tag currently names.
platform_manifest_digest() {
	local image="$1" platform="$2" os arch variant digest
	IFS=/ read -r os arch variant <<<"$platform"
	if [[ "$os" != "linux" || -z "$arch" ]]; then
		echo "platform digest: unsupported platform: $platform" >&2
		return 1
	fi

	local -a override=(--override-os "$os" --override-arch "$arch")
	[[ -z "${variant:-}" ]] || override+=(--override-variant "$variant")
	# stdout carries the digest; podman/containers-storage log lines
	# (e.g. level=info "Not using native diff for overlay") go to stderr and
	# must not be mixed into it, or the digest check below rejects a good answer.
	local inspect_output inspect_error errfile
	errfile="$(mktemp)"
	if inspect_output="$(skopeo inspect "${override[@]}" --format '{{.Digest}}' \
		"containers-storage:${image}" 2>"$errfile")" &&
		[[ "$inspect_output" =~ ^sha256:[0-9a-f]{64}$ ]]; then
		rm -f "$errfile"
		digest="$inspect_output"
		printf '%s\n' "$digest"
		return 0
	fi
	inspect_error="$(<"$errfile")"
	rm -f "$errfile"
	inspect_output="${inspect_error:-$inspect_output}"

	local reason="${inspect_output//$'\n'/ }"
	if ((${#reason} > 240)); then
		reason="${reason:0:237}..."
	fi
	echo "platform digest: cannot resolve ${platform} from local image ${image}: ${reason:-skopeo returned no diagnostic}" >&2
	return 1
}

# Succeed when the raw image index on stdin (OCI index or Docker manifest
# list, exactly as `skopeo inspect --raw` returns it) lists DIGEST as a
# manifest for PLATFORM's os and architecture. This is how a live overlay
# proves the base it built from belongs to a published index: the index
# Promote just wrote, or the one the base tag names when the overlay is bound.
#
# Membership, not selection. Promote's index carries linux/amd64 beside a
# linux/amd64/v2 entry (podman records that one as architecture "amd64/v2"),
# and which of the two a `--platform linux/amd64` pull resolves to is the
# puller's choice, not this check's. Either one belongs to the index.
# Returns 1 when DIGEST is not listed, 2 on unusable arguments.
index_lists_platform_digest() {
	local platform="$1" digest="$2" os arch
	IFS=/ read -r os arch _ <<<"$platform"
	if [[ "$os" != "linux" || -z "$arch" ]]; then
		echo "platform digest: unsupported platform: $platform" >&2
		return 2
	fi
	if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
		echo "platform digest: not a sha256 digest: ${digest:-<empty>}" >&2
		return 2
	fi
	local status=0
	jq -e --arg os "$os" --arg arch "$arch" --arg digest "$digest" '
		[.manifests[]?
		 | select(.digest == $digest)
		 | select(.platform.os == $os
		          and ((.platform.architecture // "") | split("/")[0]) == $arch)]
		| length > 0
	' >/dev/null || status=$?
	if ((status > 1)); then
		echo "platform digest: unreadable image index (jq exit ${status})" >&2
		return 2
	fi
	return "$status"
}
