#!/usr/bin/env bash
# tuna-flatpak-remote.sh — register the tuna-os Flatpak remote in the image.
#
# Sourced by install-desktop.sh via a manifest's post_install list. Only the
# remote lands in OS images; the installer frontends themselves are baked
# into live ISOs at ISO-build time (live-iso/common/src/customize-live.sh via
# tacklebox live_customize) — installed systems don't ship an OS installer.

set -euo pipefail

mkdir -p /etc/flatpak/remotes.d
curl --retry 3 --fail -sSL \
	-o /etc/flatpak/remotes.d/tuna-os.flatpakrepo \
	"https://tunaos.org/flatpak/tuna-os.flatpakrepo"
chmod 0644 /etc/flatpak/remotes.d/tuna-os.flatpakrepo
