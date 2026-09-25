#!/usr/bin/env bash
# sbom-for-rekor.sh IN OUT — write the package-level SPDX SBOM that
# attest-sbom.yml attests, and refuse one that the transparency log cannot take.
#
# rekor.sigstore.dev refuses a request body over 24 MiB with a bare
# "502 Bad Gateway" page. Measured 2026-09-25 against /api/v1/log/entries:
# 24117352 bytes got a 400 from Rekor itself, 25165928 bytes got the 502.
# `cosign attest` puts the whole predicate, base64-encoded, into that request.
#
# Syft's SPDX output has one `files` entry and one CONTAINS relationship for
# every file a package owns, so no SBOM of ours ever fitted: bonito
# base-rawhide was 37.9 MB (44,618 files), kde-nvidia-rawhide 122.7 MB
# (150,209 files). cosign-retry.sh reads a 502 as a Sigstore outage, so every
# attestation spent its 10m budget and reported SIGSTORE_OUTAGE, while Sign
# uploaded to the same log in the same minutes (tuna-os/tunaOS#2697).
#
# The attested SBOM keeps every package and every package-to-package
# relationship, and drops the per-file inventory: 3.5 MB and 7.5 MB for those
# two images. With no files listed, `filesAnalyzed` is false, and SPDX 2.3
# then forbids `packageVerificationCode`.
#
# REKOR_PREDICATE_MAX_BYTES leaves room for the base64 and envelope overhead
# (7.5 MB of predicate is a 14.1 MB request with the payload encoded twice).
# An SBOM over it fails here, with its size, and not as an outage that
# rerun-infra-failures.yml would re-run for nothing.
set -euo pipefail

: "${REKOR_PREDICATE_MAX_BYTES:=10485760}"

if [[ $# -ne 2 ]]; then
	echo "usage: $0 IN.spdx.json OUT.spdx.json" >&2
	exit 2
fi
in="$1"
out="$2"

jq -c '
  INDEX(.files[]?; .SPDXID) as $files
  | del(.files)
  | .packages |= map(
      del(.hasFiles, .packageVerificationCode) | .filesAnalyzed = false
    )
  | .relationships |= map(select(
      ($files[.spdxElementId] != null or $files[.relatedSpdxElement] != null)
      | not
    ))
' "$in" >"$out"

if ! jq -e '.spdxVersion | startswith("SPDX-")' "$out" >/dev/null ||
	! jq -e '(.packages // []) | length > 0' "$out" >/dev/null; then
	echo "::error::${in} has no SPDX packages after the per-file entries were removed" >&2
	exit 1
fi

bytes="$(stat -c %s "$out")"
if ((bytes > REKOR_PREDICATE_MAX_BYTES)); then
	echo "::error::the package-level SBOM from ${in} is ${bytes} bytes; the limit is ${REKOR_PREDICATE_MAX_BYTES}. rekor.sigstore.dev refuses a request over 24 MiB with a 502, so this attestation cannot succeed. Retrying will not help." >&2
	exit 1
fi
echo "package-level SBOM: $(stat -c %s "$in") -> ${bytes} bytes ($(jq '.packages | length' "$out") packages)"
