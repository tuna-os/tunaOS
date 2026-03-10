#!/bin/bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

# Install caffeine extension only in EPEL 10.1 or Fedora
if [[ "$IS_ALMALINUX" = true || "$IS_RHEL" = true ]]; then
	dnf install -y https://kojipkgs.fedoraproject.org//packages/gnome-shell-extension-caffeine/56/1.el10_1/noarch/gnome-shell-extension-caffeine-56-1.el10_1.noarch.rpm
else
	dnf install -y gnome-shell-extension-caffeine
fi

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

# Extra GNOME Extensions
# FIXME: gsconnect EPEL10 request: https://bugzilla.redhat.com/show_bug.cgi?id=2349097
install_from_copr ublue-os/staging 10 gnome-shell-extension-{search-light,logo-menu,gsconnect}

# GNOME version specific workarounds
GNOME_VERSION=$(gnome-shell --version | cut -d ' ' -f 3 | cut -d '.' -f 1 || echo 0)
if [ "$GNOME_VERSION" -ge 48 ]; then
	# GNOME 48: EPEL version of blur-my-shell is incompatible
	dnf -y remove gnome-shell-extension-blur-my-shell || true
	dnf -y install https://kojipkgs.fedoraproject.org//packages/gnome-shell-extension-blur-my-shell/69/1.fc43/noarch/gnome-shell-extension-blur-my-shell-69-1.fc43.noarch.rpm
fi
