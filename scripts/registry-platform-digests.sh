#!/usr/bin/env bash
# Print the platform digests of an image index as a digest spec
# ("<arch>=sha256:<hex> ..."), the value format the matrix generator reads
# from `tested-digest:` and `promoted-digest:` steps (tunaOS#3381).
#
# Usage: registry-platform-digests.sh <ref> <index-digest> [arch]
#
# The answer is given only while <ref> still resolves to <index-digest>, the
# index this run pushed. A tag that moved names some other image, and a spec
# read from it would bind evidence to an image the run never handled; that
# exits 1 with nothing on stdout. [arch] limits the spec to one platform.
#
# Environment: SKOPEO (default "skopeo"; e.g. "sudo skopeo" to use root's
# registry login).
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
	echo "usage: $0 <ref> <index-digest> [arch]" >&2
	exit 2
fi
ref=$1
expected=$2
only=${3:-}
if [[ ! "$expected" =~ ^sha256:[0-9a-f]{64}$ ]]; then
	echo "registry-platform-digests: invalid index digest '${expected}'" >&2
	exit 2
fi

read -r -a skopeo <<<"${SKOPEO:-skopeo}"
raw=$(mktemp)
trap 'rm -f "$raw"' EXIT
"${skopeo[@]}" inspect --raw "docker://${ref}" >"$raw"
actual="sha256:$(sha256sum "$raw" | cut -d' ' -f1)"
if [[ "$actual" != "$expected" ]]; then
	echo "registry-platform-digests: ${ref} resolves to ${actual}, not ${expected}" >&2
	exit 1
fi

spec=$(jq -r --arg only "$only" '
	[.manifests[]?
	 | select(.platform.os == "linux")
	 | select($only == "" or .platform.architecture == $only)
	 | "\(.platform.architecture)=\(.digest)"]
	| join(" ")' "$raw")
if [[ ! "$spec" =~ ^[a-z0-9_]+=sha256:[0-9a-f]{64}(\ [a-z0-9_]+=sha256:[0-9a-f]{64})*$ ]]; then
	echo "registry-platform-digests: ${ref} lists no linux${only:+/${only}} platform digest" >&2
	exit 1
fi
printf '%s\n' "$spec"
