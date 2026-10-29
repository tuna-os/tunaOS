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
