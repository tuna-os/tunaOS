#!/usr/bin/env bats
# An overlay flavor never rebuilds its parent — so it must re-lay the tree's
# system_files itself.
#
# `just build <variant> <flavor>-nvidia` (and -hwe/-cachyos/-asahi) chains on
# the PUBLISHED parent tag rather than rebuilding it: the Justfile takes
# localhost/<variant>:<parent> when it happens to be in storage, and otherwise
# falls back to <parent>-testing from ghcr. That fallback is deliberate (it is
# what unbroke all 24 NVIDIA LUKS cells in run 29978067348), but it means every
# file the base stage copies is frozen at whatever the published parent
# carried, while the desktop scripts, live-ISO adapters and contracts reading
# those files are always current-tree.
#
# What that cost, measured: ghcr.io/tuna-os/yellowfin:niri-testing
# (IMAGE_VERSION niri-3505bf2) ships /usr/bin/niri but has no /usr/share/niri/
# directory and no /usr/share/backgrounds/tunaos/ — its commit is not a
# descendant of 453f15b7, which added both. The niri-nvidia and niri-hwe LUKS
# cells (run 31226672079) therefore died in live customize with
# "config.kdl missing; cannot arrange installer autostart", while plain niri
# passed because the dev ISO rebuilds that one from the current tree.
#
# Verified before/after against that exact published image: desktop-niri.sh
# exits 1 on it as shipped, and exits 0 after 00-copy-files.sh runs.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
OVERLAY="${REPO_ROOT}/Containerfile.overlay"

# The desktop stage body, comment-stripped: from `FROM overlay-base AS desktop`
# to the next FROM (or EOF). Commenting a RUN out must fail these tests the
# same as deleting it.
desktop_stage() {
  awk 'tolower($0) ~ /^from[ \t]+overlay-base[ \t]+as[ \t]+desktop/ {inside=1; next}
       inside && tolower($0) ~ /^from[ \t]/ {exit}
       inside {print}' "$OVERLAY" | grep -v '^[[:space:]]*#' || true
}

@test "the overlay defines a desktop stage to assert against" {
  run desktop_stage
  [ "$status" -eq 0 ]
  [ -n "$output" ]
}

@test "the overlay desktop stage re-lays system_files" {
  # Without this the overlay inherits the parent's frozen copy of every
  # repo-shipped asset — wallpapers, plymouth theme, niri config, the logo.
  run desktop_stage
  [[ "$output" == *"00-copy-files.sh"* ]]
}

@test "the file copy runs before 90-image-info.sh, which reads what it lays down" {
  # 90-image-info.sh asserts the logo asset the repo ships at
  # /usr/share/pixmaps/tunaos.svg (system_files). Re-running the branding
  # script against the parent's stale assets is the ordering bug this pins.
  local body copy_at info_at
  body="$(desktop_stage)"
  copy_at="$(grep -n '00-copy-files.sh' <<<"$body" | head -1 | cut -d: -f1)"
  info_at="$(grep -n '90-image-info.sh' <<<"$body" | head -1 | cut -d: -f1)"
  [ -n "$copy_at" ]
  [ -n "$info_at" ]
  [ "$copy_at" -lt "$info_at" ]
}

@test "the overlay context stage actually provides the files that copy reads" {
  # 00-copy-files.sh copies /run/context/files — which only exists because the
  # context stage COPYs system_files into /files. A copy step pointed at an
  # empty directory would pass every test above and change nothing.
  local ctx
  ctx="$(awk 'tolower($0) ~ /^from[ \t]+scratch[ \t]+as[ \t]+context/ {inside=1; next}
              inside && tolower($0) ~ /^from[ \t]/ {exit}
              inside {print}' "$OVERLAY" | grep -v '^[[:space:]]*#' || true)"
  [[ "$ctx" == *"COPY system_files /files"* ]]
  [[ "$ctx" == *"build_scripts"* ]]
}

@test "the niri live adapter still requires the config it now inherits" {
  # The fatal branch in desktop-niri.sh (#1056) is what surfaced the staleness.
  # If it were softened to a warning the overlay could ship a niri ISO whose
  # installer never autostarts and nothing would fail — so pin it fatal here
  # too, next to the fix that lets it pass.
  run grep -A2 'cannot arrange installer autostart' \
    "${REPO_ROOT}/live-iso/common/src/desktop-niri.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit 1"* ]]
}

@test "the overlay desktop stage recompiles glib schemas and dconf databases" {
  # Without this, overlay-added keyfiles in /etc/dconf/db/*.d (e.g. gdm.d) are
  # uncompiled, causing GDM/GNOME runtime contract failures (#1751, #1820).
  run desktop_stage
  [[ "$output" == *"glib-compile-schemas"* ]]
  [[ "$output" == *"dconf update"* ]]
}

