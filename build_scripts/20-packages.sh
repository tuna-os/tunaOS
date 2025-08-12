#!/bin/bash

set -xeuo pipefail

printf "::group:: === 20 Packages ===\n"

MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

dnf -y remove \
	setroubleshoot

dnf -y install \
	-x gnome-extensions-app \
	almalinux-backgrounds \
	almalinux-logos \
	system-reinstall-bootc \
	gnome-disk-utility \
	distrobox \
	fastfetch \
	fpaste \
	gnome-shell-extension-{appindicator,dash-to-dock,blur-my-shell} \
	just \
	powertop \
	tuned-ppd \
	fzf \
	glow \
	wl-clipboard \
	gum \
	jetbrains-mono-fonts-all \
	buildah \
	btrfs-progs \
	xhost

if [ "${IMAGE_NAME}" == "albacore" ]; then
	dnf install -y https://kojipkgs.fedoraproject.org//packages/gnome-shell-extension-caffeine/56/1.el10_1/noarch/gnome-shell-extension-caffeine-56-1.el10_1.noarch.rpm
fi

if [ "${IMAGE_NAME}" != "albacore" ]; then
	dnf install -y gnome-shell-extension-caffeine
fi

# Everything that depends on external repositories should be after this.
# Make sure to set them as disabled and enable them only when you are going to use their packages.
# We do, however, leave crb and EPEL enabled by default.

# Tailscale
dnf config-manager --add-repo "https://pkgs.tailscale.com/stable/centos/${MAJOR_VERSION_NUMBER}/tailscale.repo"
dnf config-manager --set-disabled "tailscale-stable"
# FIXME: tailscale EPEL10 request: https://bugzilla.redhat.com/show_bug.cgi?id=2349099
dnf -y --enablerepo "tailscale-stable" install \
	tailscale

dnf -y copr enable ublue-os/packages
dnf -y copr disable ublue-os/packages

# Yellowfin Branding and tools
dnf -y --enablerepo copr:copr.fedorainfracloud.org:ublue-os:packages install \
	ublue-os-just \
	ublue-os-luks \
	ublue-os-signing \
	ublue-os-udev-rules \
	ublue-os-update-services \
	ublue-{motd,bling,rebase-helper,setup-services,polkit-rules,brew} \
	uupd \
	bluefin-schemas

# Upstream ublue-os-signing bug, we are using /usr/etc for the container signing and bootc gets mad at this
# FIXME: remove this once https://github.com/ublue-os/packages/issues/245 is closed
cp -avf /usr/etc/. /etc
rm -rvf /usr/etc

# GNOME Extensions no in EPEL
dnf -y copr enable ublue-os/staging
dnf -y copr disable ublue-os/staging
# FIXME: gsconnect EPEL10 request: https://bugzilla.redhat.com/show_bug.cgi?id=2349097
dnf -y --enablerepo copr:copr.fedorainfracloud.org:ublue-os:staging install \
	gnome-shell-extension-{search-light,logo-menu,gsconnect}

# Nerd Fonts
dnf -y copr enable che/nerd-fonts "centos-stream-${MAJOR_VERSION_NUMBER}-$(arch)"
dnf -y copr disable che/nerd-fonts
dnf -y --enablerepo "copr:copr.fedorainfracloud.org:che:nerd-fonts" install \
	nerd-fonts

# MoreWaita icon theme
dnf -y copr enable trixieua/morewaita-icon-theme
dnf -y copr disable trixieua/morewaita-icon-theme
dnf -y --enablerepo "copr:copr.fedorainfracloud.org:trixieua:morewaita-icon-theme" install \
	morewaita-icon-theme

# GNOME 48: EPEL version of blur-my-shell is incompatible
dnf -y remove gnome-shell-extension-blur-my-shell

# GNOME 48: force update xdg-desktop-portal
# dnf -y install \
# 	xdg-desktop-portal \
# 	xdg-desktop-portal-gnome

# This is required so homebrew works indefinitely.
# Symlinking it makes it so whenever another GCC version gets released it will break if the user has updated it without-
# the homebrew package getting updated through our builds.
# We could get some kind of static binary for GCC but this is the cleanest and most tested alternative. This Sucks.
dnf -y --setopt=install_weak_deps=False install gcc

printf "::endgroup::\n"
