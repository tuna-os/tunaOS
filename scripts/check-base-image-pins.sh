#!/usr/bin/env bash
# Verify every digest-pinned base image in build-config.yml still resolves.
#
# Base images are pinned by digest for reproducibility. Upstream registries
# garbage-collect untagged manifests, so a pin that was valid when it was
# written stops resolving without anything in this repo changing. When that
# happens the failure surfaces as `manifest unknown` partway into a nightly
# base build, which reads like a broken Containerfile rather than an expired
# pin -- and it takes every downstream flavor of that variant with it.
#
# It has now happened at least twice (#1788). Checking the pins directly takes
# seconds and names the problem in one line, so run it *before* the nightlies
# rather than diagnosing it afterwards.
#
# Exits non-zero if any pin fails to resolve. Prints one line per pin either
# way, because "which ones are fine" is as useful as "which one broke".
set -euo pipefail

CONFIG="${CONFIG:-.github/build-config.yml}"
YQ="${YQ:-yq}"

if ! command -v "$YQ" >/dev/null 2>&1; then
  echo "::error::yq executable not found ('$YQ'); cannot parse $CONFIG" >&2
  exit 1
fi

if [ ! -f "$CONFIG" ]; then
  echo "::error::config file not found ($CONFIG)" >&2
  exit 1
fi

# Registries serve manifest lists, image indexes and plain manifests; ask for
# all of them or a HEAD against a multi-arch tag returns 404 on content-type
# grounds and looks exactly like a GC'd digest.
ACCEPT='application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json,application/vnd.oci.image.manifest.v1+json'

# Registry quirks, all of which look like a 404 if you get them wrong:
#
#   docker.io   is a *name*, not an API host -- manifests live on
#               registry-1.docker.io and tokens come from auth.docker.io.
#   quay.io     issues anonymous pull tokens from its own /v2/auth.
#   ghcr.io     issues them from /token.
#   opensuse    serves unauthenticated; asking for a token 404s.
#
# Every helper here returns 0 even when it finds nothing, because `set -e`
# would otherwise turn "this registry needs no token" into a silent early
# exit -- which is exactly the failure mode this script exists to expose.
api_host() {
  case "$1" in
    docker.io) printf 'registry-1.docker.io' ;;
    *)         printf '%s' "$1" ;;
  esac
}

auth_header() {
  local registry="$1" repo="$2" url="" token=""
  case "$registry" in
    docker.io) url="https://auth.docker.io/token?service=registry.docker.io&scope=repository:${repo}:pull" ;;
    quay.io)   url="https://quay.io/v2/auth?service=quay.io&scope=repository:${repo}:pull" ;;
    ghcr.io)   url="https://ghcr.io/token?scope=repository:${repo}:pull" ;;
    *)         return 0 ;;
  esac
  token="$(curl -fsS --max-time 20 "$url" 2>/dev/null \
    | python3 -c 'import sys,json;print(json.load(sys.stdin).get("token",""))' 2>/dev/null || true)"
  [ -n "$token" ] && printf 'Authorization: Bearer %s' "$token"
  return 0
}

failed=0
checked=0

while IFS= read -r ref; do
  [ -n "$ref" ] || continue
  [ "$ref" = "null" ] && continue
  case "$ref" in *@sha256:*) ;; *)
    # Not digest-pinned. Not this script's problem, but say so rather than
    # silently passing -- an unpinned base is its own kind of surprise.
    echo "SKIP  (not digest-pinned)  ${ref}"
    continue ;;
  esac

  digest="${ref##*@}"
  before_at="${ref%@*}"
  name="${before_at%%:*}"          # strip any :tag
  registry="${name%%/*}"
  repo="${name#*/}"

  hdr="$(auth_header "$registry" "$repo")"
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 \
      -H "Accept: ${ACCEPT}" ${hdr:+-H "$hdr"} \
      "https://$(api_host "$registry")/v2/${repo}/manifests/${digest}" || echo 000)"

  checked=$((checked + 1))
  if [ "$code" = "200" ]; then
    echo "ok    ${code}  ${ref}"
  else
    echo "FAIL  ${code}  ${ref}"
    echo "::error::base image pin no longer resolves (HTTP ${code}): ${ref}"
    failed=$((failed + 1))
  fi
done < <("$YQ" -r '.variants[].base_image // empty' "$CONFIG" | sort -u)

echo
echo "checked ${checked} digest-pinned base image(s); ${failed} unresolvable"

# ── Architecture honesty (green criterion 10, GREEN-MASTER-PLAN W8) ─────────
# A variant may not declare a platform its base image cannot provide: the
# result is a guaranteed-red cell every night that no change in this repo can
# clear (hummingbird declared linux/arm64 against a source that 404'd,
# #1755 §3 — four dead cells nightly until someone read the logs). Declaring
# an unsatisfiable architecture should fail THIS check, loudly, at config
# time.
#
# Platform → manifest architecture: linux/amd64/v2 is a microarchitecture
# level of amd64, so it maps to amd64; the base manifest cannot and need not
# distinguish it.
arch_failed=0
arch_checked=0
echo
while IFS=$'\t' read -r variant ref platforms; do
  [ -n "$ref" ] && [ "$ref" != "null" ] || continue
  case "$ref" in *@sha256:*) ;; *) continue ;; esac

  digest="${ref##*@}"
  before_at="${ref%@*}"
  name="${before_at%%:*}"
  registry="${name%%/*}"
  repo="${name#*/}"

  hdr="$(auth_header "$registry" "$repo")"
  body="$(curl -fsS --max-time 30 -H "Accept: ${ACCEPT}" ${hdr:+-H "$hdr"} \
      "https://$(api_host "$registry")/v2/${repo}/manifests/${digest}" 2>/dev/null || true)"
  [ -n "$body" ] || continue  # resolution failures already reported above

  archs="$(printf '%s' "$body" | python3 -c '
import json, sys
doc = json.load(sys.stdin)
entries = doc.get("manifests")
if entries is None:
    # A plain (single-arch) manifest carries its architecture in the config
    # blob, not here; report the sentinel rather than guessing.
    print("SINGLE")
else:
    seen = sorted({m.get("platform", {}).get("architecture", "?")
                   for m in entries
                   if m.get("platform", {}).get("os") != "unknown"})
    print(" ".join(seen))
' 2>/dev/null || echo '?')"

  for platform in ${platforms//,/ }; do
    arch="${platform#linux/}"
    arch="${arch%%/*}"
    arch_checked=$((arch_checked + 1))
    if [ "$archs" = "SINGLE" ]; then
      # Cannot verify cheaply; only complain when the variant claims more
      # than the one architecture a single manifest can possibly hold.
      distinct="$(printf '%s\n' ${platforms//,/ } | sed 's|linux/||; s|/.*||' | sort -u | wc -l)"
      if [ "$distinct" -gt 1 ]; then
        echo "ARCH?  ${variant}: ${platform} declared but ${name} pins a single-arch manifest"
        echo "::warning::${variant} declares ${platform} but its base image pin is a single-architecture manifest — at most one declared architecture can be real"
      fi
      continue
    fi
    case " $archs " in
      *" $arch "*) echo "arch   ok  ${variant}: ${platform} (base has: ${archs})" ;;
      *)
        echo "ARCH  FAIL ${variant}: ${platform} — base ${name} provides only [${archs}]"
        echo "::error::${variant} declares ${platform} but its base image provides only [${archs}] — a guaranteed-red cell nightly. Drop the platform or fix the base pin (criterion arch_honesty, W8)."
        arch_failed=$((arch_failed + 1))
        ;;
    esac
  done
done < <("$YQ" -r '.variants[] | [.id, (.base_image // ""), ((.platforms // []) | join(","))] | @tsv' "$CONFIG")

echo
echo "checked ${arch_checked} declared platform(s); ${arch_failed} unsatisfiable"

if [ "$failed" -gt 0 ]; then
  echo "::error::${failed} base image pin(s) have been garbage-collected upstream. Re-pin them to the tag's current digest before the next nightly (see #1788)."
  exit 1
fi
if [ "$arch_failed" -gt 0 ]; then
  exit 1
fi
