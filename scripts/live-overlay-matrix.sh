#!/usr/bin/env bash
# Print the live-overlay build matrix as {"include":[{variant, flavor,
# platform, safeplatform, runner}, ...]}.
#
# Usage: scripts/live-overlay-matrix.sh [VARIANT|all] [FLAVOR|all]
#
# One selector for both callers: live-overlay.yml's generate-matrix job and
# scripts/dispatch-live-overlay.sh, which asks after every Promote whether the
# promoted cell has an overlay to rebind. Two copies of this filter would
# drift, and a drifted copy either leaves a published overlay stale (tacklebox
# refuses it, fail-closed since #425) or dispatches a run for a cell the
# workflow then builds nothing for.
#
# Overlays carry the per-desktop live payload (installer flatpak, autologin,
# polkit) the browser ISO builder grafts in as
# live-overlay:<variant>-<flavor>[-<safeplatform>]. Filter on build_image
# (NOT build_iso): the browser builds ISOs from any published *image*,
# including image-only variants CI never cuts an ISO for — sailfin is exactly
# that case, so it had no overlay and booted with no installer. New variants
# are picked up automatically instead of the old yellowfin-only default.
#
# EXACT FILTER (jq, below): build_image == true AND the flavor id matches a
# desktop family with an optional hardware/kernel layer suffix —
# ^(gnome|kde|cosmic|niri|xfce|pantheon)(-(hwe|nvidia|nvidia-hwe|cachyos|zfs))?$.
# `tuna` is excluded until its greetd session is supported by the production
# live baseline. The filter includes -hwe/-nvidia/-nvidia-hwe/-cachyos/-zfs
# layers CI qualifies, and excludes:
#   * base and base-* (no desktop, no live session to customize),
#   * *-asahi / *-t2 (device-specific install paths -- the asahi-installer /
#     T2 flows, not the live ISO -- even where build-config marks them
#     buildable),
#   * anything build_image: false (e.g. yellowfin gnome-nvidia-hwe,
#     tunaOS#2518: builds but cannot mount its own root).
# Each surviving flavor fans out to one row per declared platform (flavor
# platforms, else variant platforms; linux/amd64/v2 is a CPU-feature variant,
# not a target arch, so only linux/amd64 and linux/arm64 qualify -- same
# exclusion build-variant.yml applies).
set -euo pipefail
want_variant="${1:-all}"
want_flavor="${2:-all}"
# shellcheck source=lib/build-config.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/build-config.sh"
config="$(tunaos_build_config)"

yq -o json "$config" | jq -c \
	--arg v "$want_variant" --arg f "$want_flavor" '{
    include: [
      . as $root | .variants[] as $var | $var.flavors[]
      | select(.build_image == true)
      | select(.id | test("^(gnome|kde|cosmic|niri|xfce|pantheon)(-(hwe|nvidia|nvidia-hwe|cachyos|zfs))?$"))
      | select($v == "all" or $var.id == $v)
      | select($f == "all" or .id == $f)
      | {variant: $var.id, flavor: .id,
         platforms: (.platforms // $var.platforms // $root.config.global_platforms // ["linux/amd64"])}
      | .platforms as $plats
      | {variant: .variant, flavor: .flavor,
         platform: $plats[]}
      | select(.platform == "linux/amd64" or .platform == "linux/arm64")
      | {variant, flavor, platform,
         safeplatform: (.platform | gsub("/"; "-")),
         runner: (if .platform == "linux/arm64" then "ubuntu-24.04-arm" else "ubuntu-latest" end)}
    ]
  }'
