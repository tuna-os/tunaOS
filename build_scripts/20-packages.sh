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

# MoreWaita icon theme — from upstream source, not the trixieua/
# morewaita-icon-theme personal COPR. tunaOS#1323's package-sourcing policy
# audit (#1453) flagged that COPR as a real violation: a single-maintainer
# personal repackage of one static-file package, with no build step of its
# own. Upstream ships install.sh, which just copies icon files into
# THEMEDIR — clone at a pinned tag and run it directly instead of trusting
# a third party's repackage of the same files.
if [[ "${DESKTOP_FLAVOR}" == *"gnome"* ]]; then
	MOREWAITA_VERSION="v49"
	# git is not guaranteed present on the Fedora/EL10 RPM path at this build
	# stage (kcm-ublue.sh's own BUILD_DEPS list has to install it explicitly
	# for the same reason) — install it here rather than assume it.
	dnf_retry -y install git
	MOREWAITA_SRC=$(mktemp -d)
	git clone --depth 1 --branch "${MOREWAITA_VERSION}" \
		https://github.com/somepaulo/MoreWaita.git "${MOREWAITA_SRC}"
	# install.sh's own final step (gtk-update-icon-cache) is a live-desktop
	# concern, not guaranteed present in a build container — best-effort,
	# same tolerance as the rest of this file's non-essential installs.
	if THEMEDIR=/usr/share/icons/MoreWaita/ bash "${MOREWAITA_SRC}/install.sh"; then
		echo "MoreWaita ${MOREWAITA_VERSION} icon theme installed."
	else
		echo "Warning: MoreWaita icon theme install reported a non-fatal error (icon cache update?)."
	fi
	rm -rf "${MOREWAITA_SRC}"
fi

# This is required so homebrew works indefinitely.
# Symlinking it makes it so whenever another GCC version gets released it will break if the user has updated it without-
# the homebrew package getting updated through our builds.
# We could get some kind of static binary for GCC but this is the cleanest and most tested alternative. This Sucks.
dnf -y --setopt=install_weak_deps=False install gcc

printf "::endgroup::\n"
