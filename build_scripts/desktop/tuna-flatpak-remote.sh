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

# The project's own remote: [flatpak_preinstall] remote_url in tunaos.toml,
# through the identity adapter. Read in a subshell, because this file is
# sourced into install-desktop.sh and must not leak the adapter's variables.
# Empty means the project runs no Flatpak remote, and none is registered.
tuna_identity_env="$(dirname "${BASH_SOURCE[0]}")/../lib/identity.env"
if [[ ! -r "${tuna_identity_env}" ]]; then
	echo "ERROR: ${tuna_identity_env} is missing or unreadable; run scripts/config.py generate-identity" >&2
	return 1
fi
tuna_remote_url="$(bash -c 'source "$1" && printf %s "${TUNAOS_FLATPAK_REMOTE_URL}"' _ "${tuna_identity_env}")"

mkdir -p /etc/flatpak/remotes.d
if [[ -n "${tuna_remote_url}" ]]; then
	curl --retry 3 --fail -sSL \
		-o /etc/flatpak/remotes.d/tuna-os.flatpakrepo \
		"${tuna_remote_url}"
	chmod 0644 /etc/flatpak/remotes.d/tuna-os.flatpakrepo
else
	echo "No [flatpak_preinstall] remote_url in tunaos.toml; not registering the tuna-os remote"
fi

# Flathub: skip the download when 26-packages-post.sh already baked it (rpm
# and apt bases); fetch it on the bases that never run that script.
if [[ ! -s /etc/flatpak/remotes.d/flathub.flatpakrepo ]]; then
	curl --retry 3 --fail -sSL \
		-o /etc/flatpak/remotes.d/flathub.flatpakrepo \
		"https://dl.flathub.org/repo/flathub.flatpakrepo"
	chmod 0644 /etc/flatpak/remotes.d/flathub.flatpakrepo
fi
