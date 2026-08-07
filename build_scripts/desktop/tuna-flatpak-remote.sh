#!/usr/bin/env bash
# tuna-flatpak-remote.sh — register the Flatpak remotes in the image.
#
# Sourced by install-desktop.sh via a manifest's post_install list. Only the
# remotes land in OS images; the installer frontends themselves are baked
# into live ISOs at ISO-build time (live-iso/common/src/customize-live.sh via
# tacklebox live_customize) — installed systems don't ship an OS installer.
#
# TWO remotes, and the second closes a real gap. Flathub used to be baked
# only by 26-packages-post.sh, which the marlin (Containerfile.arch), guppy
# (Containerfile.gentoo) and sailfin (Containerfile.opensuse) builds never
# run — so those installed systems had only the tuna-os remote, no Flathub,
# and everything Flathub-sourced (Bazaar via flatpak-preinstall.sh, anything
# a user tries to install) silently had no source. This script runs through
# install-desktop.sh's post_install on EVERY base (the apt path falls
# through to the shared tail since tunaOS#959), which makes it the one place
# that covers all variants. Idempotent next to 26-packages-post.sh: on bases
# that run both, the file is already present and the fetch is skipped.

set -euo pipefail

mkdir -p /etc/flatpak/remotes.d
curl --retry 3 --fail -sSL \
	-o /etc/flatpak/remotes.d/tuna-os.flatpakrepo \
	"https://tunaos.org/flatpak/tuna-os.flatpakrepo"
chmod 0644 /etc/flatpak/remotes.d/tuna-os.flatpakrepo

# Flathub: skip the download when 26-packages-post.sh already baked it (rpm
# and apt bases); fetch it on the bases that never run that script.
if [[ ! -s /etc/flatpak/remotes.d/flathub.flatpakrepo ]]; then
	curl --retry 3 --fail -sSL \
		-o /etc/flatpak/remotes.d/flathub.flatpakrepo \
		"https://dl.flathub.org/repo/flathub.flatpakrepo"
	chmod 0644 /etc/flatpak/remotes.d/flathub.flatpakrepo
fi
