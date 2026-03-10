#!/bin/bash

set -xeuo pipefail

printf "::group:: === 20 Packages ===\n"

source /run/context/build_scripts/lib.sh

# Install OS-specific branding
if [[ $IS_FEDORA == true ]]; then
	dnf -y install fedora-logos
fi
if [[ $IS_ALMALINUX == true ]]; then
	dnf -y install almalinux-backgrounds almalinux-logos
fi
if [[ $IS_CENTOS == true ]]; then
	dnf -y install centos-backgrounds centos-logos
fi
# RHEL: no redistribution-safe branding packages; skip OS branding install

# Tailscale
TUNA_CACHE="/tmp/tuna-packages"
if [ -d "${TUNA_CACHE}" ] && find "${TUNA_CACHE}" -name "tailscale[-_]*.rpm" -type f | grep -q .; then
	echo "Installing Tailscale from TunaOS packages..."
	TAILSCALE_RPMS=$(find "${TUNA_CACHE}" -name "tailscale[-_]*.rpm" -type f)
	# shellcheck disable=SC2086
	dnf -y install ${TAILSCALE_RPMS}
else
	echo "Tailscale not found in TunaOS cache, falling back to upstream repository"
	if [[ $IS_FEDORA == true ]]; then
		dnf config-manager addrepo --from-repofile="https://pkgs.tailscale.com/stable/fedora/tailscale.repo"
		# Retry with backoff for HTTP/2 stream errors
		for attempt in {1..3}; do
			if dnf -y install tailscale; then
				break
			fi
			if [[ $attempt -lt 3 ]]; then
				echo "Tailscale install failed, retrying in 10 seconds..."
				sleep 10
			fi
		done
	else
		dnf config-manager --add-repo "https://pkgs.tailscale.com/stable/centos/${MAJOR_VERSION_NUMBER}/tailscale.repo"
		dnf config-manager --set-disabled "tailscale-stable"
		# Retry with backoff for HTTP/2 stream errors
		for attempt in {1..3}; do
			if dnf -y --enablerepo "tailscale-stable" install tailscale; then
				break
			fi
			if [[ $attempt -lt 3 ]]; then
				echo "Tailscale install failed, retrying in 10 seconds..."
				sleep 10
			fi
		done
	fi
fi

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	/run/context/build_scripts/kde.sh extra
else
	/run/context/build_scripts/gnome.sh extra
fi

# Upstream ublue-os-signing bug, we are using /usr/etc for the container signing and bootc gets mad at this
# FIXME: remove this once https://github.com/ublue-os/packages/issues/245 is closed
if [ -d /usr/etc ]; then
	cp -avf /usr/etc/. /etc
	rm -rvf /usr/etc
fi

# MoreWaita icon theme from TunaOS packages
TUNA_CACHE="/tmp/tuna-packages"
if [ -d "${TUNA_CACHE}" ] && find "${TUNA_CACHE}" -name "morewaita-icon-theme-*.rpm" -type f | grep -q .; then
	echo "Installing MoreWaita icon theme from TunaOS packages..."
	dnf -y install "${TUNA_CACHE}"/morewaita-icon-theme-*.rpm
else
	echo "Warning: MoreWaita not found in TunaOS packages, falling back to COPR"
	install_from_copr trixieua/morewaita-icon-theme morewaita-icon-theme
fi

# This is required so homebrew works indefinitely.
# Symlinking it makes it so whenever another GCC version gets released it will break if the user has updated it without-
# the homebrew package getting updated through our builds.
# We could get some kind of static binary for GCC but this is the cleanest and most tested alternative. This Sucks.
dnf -y --setopt=install_weak_deps=False install gcc

printf "::endgroup::\n"