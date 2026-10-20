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
	if digest="$(skopeo inspect "${override[@]}" --format '{{.Digest}}' \
		"containers-storage:${image}" 2>/dev/null)" &&
		[[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
		printf '%s\n' "$digest"
		return 0
	fi

	echo "platform digest: cannot resolve ${platform} from local image ${image}" >&2
	return 1
}
