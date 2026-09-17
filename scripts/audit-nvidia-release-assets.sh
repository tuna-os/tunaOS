#!/usr/bin/env bash
# Audit that every NVIDIA edition is actually downloadable.
#
# WHAT THIS USED TO CHECK, AND WHY IT NEVER PASSED
#
# The first version looked for a GitHub Release per flavor, tagged
# "<flavor>-<date>", carrying at least one asset. It was red on all 15 runs it
# ever had, because this repository does not publish ISOs that way:
#
#   * reusable-build-artifacts.yml takes `attach-release` as an input and it
#     DEFAULTS TO FALSE, so "Attach ISO to GitHub Release" is skipped on every
#     cell. A successful nvidia ISO job shows exactly that, with
#     "Upload ISO to Cloudflare R2" succeeding beside it.
#   * The releases that do exist are per DESKTOP, not per flavor
#     (gnome-20260916, kde-20260916, ...), so no tag ever started with
#     "gnome-nvidia-".
#   * Every one of those releases carries 0 assets.
#
# A gate that cannot pass reports nothing. This one also asked about a flavor
# that does not exist: its hardcoded list named `gnome50-nvidia`, which is in
# no variant in .github/build-config.yml.
#
# WHAT IT CHECKS NOW
#
# The real channel. reusable-build-artifacts.yml publishes each ISO to
#
#   R2:<bucket>/live-isos/<variant>-<flavor>-latest.iso
#
# for linux/amd64, which is the documented download path users wget
# (docs/TESTING.md). This asserts that object exists for every NVIDIA cell the
# matrix says it builds.
#
# The flavor list is DERIVED from .github/build-config.yml rather than
# hardcoded, because the hardcoded one had already drifted away from reality
# and nobody noticed for 15 runs.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
config="${TUNAOS_BUILD_CONFIG:-${repo_root}/.github/build-config.yml}"

command -v yq >/dev/null || {
	echo "FAIL: yq is required to read ${config}" >&2
	exit 1
}

# Credentials absent means this is a fork or a local run, not a fault to
# report. The upload step and prune-r2.yml both take the same line.
if [[ -z "${RCLONE_CONFIG_R2_ACCESS_KEY_ID:-}" || -z "${R2_BUCKET:-}" ]]; then
	echo "::notice::R2 credentials not configured; skipping the NVIDIA download audit."
	exit 0
fi

command -v rclone >/dev/null || {
	echo "FAIL: rclone is required to list R2" >&2
	exit 1
}

# Every (variant, flavor) the matrix says ships an NVIDIA ISO.
mapfile -t cells < <(
	yq -o=json '.' "$config" |
		jq -r '.variants[]
        | .id as $v
        | .flavors[]
        | select(.build_image == true and .build_iso == true)
        | select(.id | test("nvidia"))
        | "\($v) \(.id)"'
)

if ((${#cells[@]} == 0)); then
	echo "FAIL: no NVIDIA ISO cells found in ${config}" >&2
	echo "Either the matrix stopped building them, or this query is wrong." >&2
	exit 1
fi

# One listing, then look the names up locally. Per-object rclone calls would
# be one round trip per cell for no extra information.
listing="$(rclone lsf --files-only "R2:${R2_BUCKET}/live-isos/")"

fail=0
for cell in "${cells[@]}"; do
	read -r variant flavor <<<"$cell"
	want="${variant}-${flavor}-latest.iso"
	if grep -qxF "$want" <<<"$listing"; then
		echo "ok: ${want}"
	else
		echo "MISSING ${variant}:${flavor}: live-isos/${want} is not in R2" >&2
		fail=1
	fi
done

if ((fail)); then
	echo "NVIDIA DOWNLOAD AUDIT FAILED: an advertised NVIDIA edition has no ISO to download" >&2
	exit 1
fi

echo "NVIDIA DOWNLOAD AUDIT PASSED (${#cells[@]} cells)"
