#!/usr/bin/env bash
# pin-image-digest.sh <image ref> — print "<ref>@<digest> <digest>".
#
# The digest is the sha256 of the manifest the registry serves for the ref:
# for a multi-arch tag that is the index digest, the same value Promote reports
# as index_digest and `skopeo inspect` shows as Digest. A ref that already
# carries @sha256: is printed unchanged. Used by build-image-inner.sh to build
# a hardware overlay FROM exactly one parent and to label the image with it.
#
# Environment: SKOPEO (optional) names the skopeo binary; tests stub it.
set -euo pipefail

ref="${1:?usage: pin-image-digest.sh <image ref>}"
SKOPEO="${SKOPEO:-skopeo}"

if [[ "${ref}" == *@sha256:* ]]; then
	digest="${ref##*@}"
	pinned="${ref}"
else
	raw="$(mktemp)"
	trap 'rm -f "${raw}"' EXIT
	if ! "${SKOPEO}" inspect --raw --retry-times 3 "docker://${ref}" >"${raw}" || [[ ! -s "${raw}" ]]; then
		echo "ERROR: could not read the manifest of ${ref}" >&2
		exit 1
	fi
	digest="sha256:$(sha256sum "${raw}" | cut -d' ' -f1)"
	pinned="${ref}@${digest}"
fi

if [[ ! "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
	echo "ERROR: ${ref} resolved to '${digest}', not a sha256 digest" >&2
	exit 1
fi
printf '%s %s\n' "${pinned}" "${digest}"
