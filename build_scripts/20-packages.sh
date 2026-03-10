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

# Tailscale - resolve latest version via GitHub releases (same as Homebrew livecheck :github_latest strategy)
tailscale_version="$(curl -fsSL -o /dev/null -w '%{url_effective}' https://github.com/tailscale/tailscale/releases/latest | grep -oP 'v\K[\d.]+')"
if [[ -z "${tailscale_version}" ]]; then
	echo "Failed to determine latest Tailscale version from GitHub" >&2
	exit 1
fi

rpm_arch="$(uname -m)"
if [[ "${rpm_arch}" == "x86_64_v2" ]]; then
	rpm_arch="x86_64"
fi

if [[ $IS_FEDORA == true ]]; then
	repo_base="https://pkgs.tailscale.com/stable/fedora/${MAJOR_VERSION_NUMBER}/${rpm_arch}"
else
	repo_base="https://pkgs.tailscale.com/stable/centos/${MAJOR_VERSION_NUMBER}/${rpm_arch}"
fi

rpm_url="${repo_base}/tailscale_${tailscale_version}_${rpm_arch}.rpm"
echo "Installing Tailscale ${tailscale_version} from URL: ${rpm_url}"

for attempt in 1 2 3; do
	if dnf -y install "${rpm_url}"; then
		break
	fi
	if [[ ${attempt} -lt 3 ]]; then
		echo "Tailscale install failed, retrying in 10 seconds..."
		sleep 10
	else
		echo "Failed to install Tailscale from URL after retries" >&2
		exit 1
	fi
done

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	/run/context/build_scripts/kde.sh extra
elif [[ "${DESKTOP_FLAVOR}" == "niri" ]]; then
	/run/context/build_scripts/niri.sh extra
else
	echo "Skipping DE-specific extra packages (DESKTOP_FLAVOR='${DESKTOP_FLAVOR}')"
fi

# Upstream ublue-os-signing bug, we are using /usr/etc for the container signing and bootc gets mad at this
# FIXME: remove this once https://github.com/ublue-os/packages/issues/245 is closed
if [ -d /usr/etc ]; then
	cp -avf /usr/etc/. /etc
	rm -rvf /usr/etc
fi

# MoreWaita icon theme
install_from_copr trixieua/morewaita-icon-theme morewaita-icon-theme

# This is required so homebrew works indefinitely.
# Symlinking it makes it so whenever another GCC version gets released it will break if the user has updated it without-
# the homebrew package getting updated through our builds.
# We could get some kind of static binary for GCC but this is the cleanest and most tested alternative. This Sucks.
dnf -y --setopt=install_weak_deps=False install gcc

printf "::endgroup::\n"