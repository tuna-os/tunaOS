#!/bin/bash

set -xeuo pipefail

printf "::group:: === 20 Packages ===\n"

source /run/context/build_scripts/lib.sh

# ── apt (Ubuntu/Debian) path ──────────────────────────────────────────
if [[ "$PKG_MGR" == "apt" ]]; then
	# GCC for Homebrew (same rationale as RPM path)
	pkg_install gcc

	# Tailscale — Configure repository based on distro
	if [[ "$IS_UBUNTU" == true ]]; then
		curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
		curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list | tee /etc/apt/sources.list.d/tailscale.list
	else
		curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
		curl -fsSL https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list | tee /etc/apt/sources.list.d/tailscale.list
	fi
	pkg_install tailscale

	printf "::endgroup::\n"
	exit 0
fi
# ── dnf (RPM) path continues below ────────────────────────────────────

# Install OS-specific branding
if [[ $IS_FEDORA == true ]]; then
	dnf_retry -y install fedora-logos
fi
if [[ $IS_ALMALINUX == true ]]; then
	dnf_retry -y install almalinux-backgrounds almalinux-logos
fi
if [[ $IS_CENTOS == true ]]; then
	dnf_retry -y install centos-backgrounds centos-logos
fi
# RHEL: no redistribution-safe branding packages; skip OS branding install

# Ensure unzip is available for font installation in 26-packages-post.sh
dnf_retry -y install unzip

if [[ "${DESKTOP_FLAVOR}" == "niri" ]]; then
	/run/context/build_scripts/desktop/niri.sh extra
else
	echo "Skipping DE-specific extra packages (DESKTOP_FLAVOR='${DESKTOP_FLAVOR}')"
fi

# Tailscale — fetch repo file directly into /etc/yum.repos.d/
local_ts_ver="${MAJOR_VERSION_NUMBER:-10}"
if [[ ! "$local_ts_ver" =~ ^[0-9]+$ ]]; then local_ts_ver=10; fi

if [[ $IS_FEDORA == true ]]; then
	curl -fsSL -o /etc/yum.repos.d/tailscale.repo "https://pkgs.tailscale.com/stable/fedora/tailscale.repo" || true
else
	curl -fsSL -o /etc/yum.repos.d/tailscale.repo "https://pkgs.tailscale.com/stable/centos/${local_ts_ver}/tailscale.repo" || true
fi
sed -i 's/enabled=1/enabled=0/g' /etc/yum.repos.d/tailscale.repo 2>/dev/null || true
dnf -y --enablerepo "tailscale-stable" install tailscale || true

# Upstream ublue-os-signing bug: the package used /usr/etc for container
# signing; bootc rejects non-/etc paths. Fixed upstream (ublue-os/packages#245
# closed). Remove this workaround once the updated package is in all base images.
# The guard is a no-op when /usr/etc doesn't exist.
if [ -d /usr/etc ]; then
	cp -avf /usr/etc/. /etc
	rm -rvf /usr/etc
fi

# MoreWaita icon theme
if [[ "${DESKTOP_FLAVOR}" == *"gnome"* ]]; then
	install_from_copr trixieua/morewaita-icon-theme morewaita-icon-theme
fi

# This is required so homebrew works indefinitely.
# Symlinking it makes it so whenever another GCC version gets released it will break if the user has updated it without-
# the homebrew package getting updated through our builds.
# We could get some kind of static binary for GCC but this is the cleanest and most tested alternative. This Sucks.
dnf -y --setopt=install_weak_deps=False install gcc

printf "::endgroup::\n"
