#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 20 KDE Packages ===\n"

source /run/context/build_scripts/lib.sh

if [[ $IS_FEDORA == true ]]; then
    dnf -y install fedora-logos
fi
if [[ $IS_ALMALINUX == true ]]; then
    dnf -y install almalinux-backgrounds almalinux-logos
fi
if [[ $IS_CENTOS == true ]]; then
    dnf -y install centos-backgrounds centos-logos
fi

if [[ $IS_FEDORA == true ]]; then
    dnf config-manager addrepo --from-repofile="https://pkgs.tailscale.com/stable/fedora/tailscale.repo"
    dnf -y install tailscale
else
    dnf config-manager --add-repo "https://pkgs.tailscale.com/stable/centos/${MAJOR_VERSION_NUMBER}/tailscale.repo"
    dnf config-manager --set-disabled "tailscale-stable"
    dnf -y --enablerepo "tailscale-stable" install tailscale
fi

install_from_copr ublue-os/packages \
    ublue-os-just \
    ublue-os-luks \
    ublue-os-signing \
    ublue-os-udev-rules \
    ublue-os-update-services \
    ublue-{motd,bling,rebase-helper,setup-services,polkit-rules,brew} \
    uupd \
    kcm_ublue \
    krunner-bazaar

if [ -d /usr/etc ]; then
    cp -avf /usr/etc/. /etc
    rm -rvf /usr/etc
fi

install_from_copr trixieua/morewaita-icon-theme morewaita-icon-theme

# Keep GCC available for homebrew runtime compatibility.
dnf -y --setopt=install_weak_deps=False install gcc

printf "::endgroup::\n"
