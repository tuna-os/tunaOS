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

# Install caffeine extension only in EPEL 10.1 or Fedora
echo "$IMAGE_NAME"
detected_os
cat /etc/os-release
if [[ "$IS_ALMALINUX" = true || "$IS_RHEL" = true ]]; then
	dnf install -y https://kojipkgs.fedoraproject.org//packages/gnome-shell-extension-caffeine/56/1.el10_1/noarch/gnome-shell-extension-caffeine-56-1.el10_1.noarch.rpm
else
	dnf install -y gnome-shell-extension-caffeine
fi

# Everything that depends on external repositories should be after this.

# Tailscale
if [[ $IS_FEDORA == true ]]; then
	dnf config-manager --add-repo "https://pkgs.tailscale.com/stable/fedora/tailscale.repo"
else
	dnf config-manager --add-repo "https://pkgs.tailscale.com/stable/centos/${MAJOR_VERSION_NUMBER}/tailscale.repo"
fi
dnf config-manager --set-disabled "tailscale-stable"
# FIXME: tailscale EPEL10 request: https://bugzilla.redhat.com/show_bug.cgi?id=2349099
dnf -y --enablerepo "tailscale-stable" install tailscale

# ublue-os packages
install_from_copr ublue-os/packages \
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
if [ -d /usr/etc ]; then
	cp -avf /usr/etc/. /etc
	rm -rvf /usr/etc
fi

# Extra GNOME Extensions
# FIXME: gsconnect EPEL10 request: https://bugzilla.redhat.com/show_bug.cgi?id=2349097
install_from_copr ublue-os/staging gnome-shell-extension-{search-light,logo-menu,gsconnect}

# MoreWaita icon theme
install_from_copr trixieua/morewaita-icon-theme morewaita-icon-theme

# GNOME version specific workarounds
GNOME_VERSION=$(gnome-shell --version | cut -d ' ' -f 3 | cut -d '.' -f 1)
if [ "$GNOME_VERSION" -ge 48 ]; then
	# GNOME 48: EPEL version of blur-my-shell is incompatible
	dnf -y remove gnome-shell-extension-blur-my-shell
	dnf -y install https://kojipkgs.fedoraproject.org//packages/gnome-shell-extension-blur-my-shell/69/1.fc43/noarch/gnome-shell-extension-blur-my-shell-69-1.fc43.noarch.rpm
fi

# This is required so homebrew works indefinitely.
# Symlinking it makes it so whenever another GCC version gets released it will break if the user has updated it without-
# the homebrew package getting updated through our builds.
# We could get some kind of static binary for GCC but this is the cleanest and most tested alternative. This Sucks.
dnf -y --setopt=install_weak_deps=False install gcc

printf "::endgroup::\n"
