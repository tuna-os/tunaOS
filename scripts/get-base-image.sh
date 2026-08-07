#!/usr/bin/env bash
# get-base-image.sh — variant → OS base image reference.
#
# The mapping lives in .github/build-config.yml (`base_image:` per variant).
# This script used to carry a second, hardcoded copy of it, and the two
# drifted — silently, because nothing compared them:
#
#   bonito    build-config: fedora-bootc:44      here: fedora-bootc:43
#   guppy     build-config: stage3@sha256:9d03b48…  here: stage3:latest
#   gurnard   build-config: ubuntu:noble         here: absent entirely
#
# The missing gurnard entry is the "Unknown variant: gurnard" in #1014. The
# bonito and guppy rows are worse than that failure, because they don't fail:
# a build that went through this script got a different base image than one
# that read the config, with no error either way.
#
# .github/workflows/reusable-build-image.yml hides the whole class of bug —
# when this script exits non-zero it falls back to reading base_image out of
# build-config.yml itself. That is why gurnard built in CI and only died on
# the `just build` path (Justfile:126), which has no fallback, and so only
# surfaced in the LUKS E2E sweep.
#
# So: read the config, and keep exactly one thing here that genuinely is not
# in it — see PLATFORM OVERRIDES and OFF-MATRIX VARIANTS below.
#
# Usage: get-base-image.sh <variant> [platform]

set -euo pipefail

variant="${1:?usage: get-base-image.sh <variant> [platform]}"
# Optional: target platform (e.g. linux/arm64).
platform="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${TUNAOS_BUILD_CONFIG:-${SCRIPT_DIR}/../.github/build-config.yml}"
YQ="${YQ:-yq}"

# ── PLATFORM OVERRIDES ───────────────────────────────────────────────────────
# Variants whose build-config base is single-arch declare an arm64-specific
# base here. docker.io/archlinux is x86_64-only; the ALARM base is built by
# build-archlinuxarm-base.yml (#778). build-config.yml has one base_image per
# variant and no per-platform axis, so this cannot be expressed there yet.
if [[ "$platform" == *arm64* ]]; then
	case "$variant" in
	"marlin")
		echo "ghcr.io/tuna-os/archlinuxarm:latest"
		exit 0
		;;
	esac
fi

# ── OFF-MATRIX VARIANTS ──────────────────────────────────────────────────────
# Variants that are deliberately absent from build-config.yml because they are
# not part of the public build matrix. redfin needs an RHSM subscription to
# pull its base at all (scripts/lifecycle-test.sh:51), so it is driven only by
# `just corral-build` / `just lifecycle-test`, never by the CI matrix.
case "$variant" in
"redfin")
	echo "registry.redhat.io/rhel10/rhel-bootc:latest"
	exit 0
	;;
esac

if [[ ! -r "$CONFIG" ]]; then
	echo "ERROR: cannot read build config: $CONFIG" >&2
	exit 1
fi

base="$("$YQ" -r ".variants[] | select(.id == \"${variant}\") | .base_image" "$CONFIG" 2>/dev/null || true)"

# yq prints "null" for a variant that exists with no base_image, and nothing at
# all for a variant that does not exist. Both mean "no answer" — never let
# either reach a caller as if it were an image reference.
if [[ -z "$base" || "$base" == "null" ]]; then
	echo "Unknown variant: $variant" >&2
	exit 1
fi

echo "$base"
