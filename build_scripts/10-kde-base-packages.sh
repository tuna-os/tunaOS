#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 10 KDE Base Packages ===\n"

source /run/context/build_scripts/lib.sh

if [[ $IS_CENTOS == true ]]; then
    dnf remove -y subscription-manager
fi

dnf -y install 'dnf-command(versionlock)'
dnf versionlock add kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt

if [[ $IS_FEDORA == true ]]; then
    dnf -y "do" \
        --action=install 'dnf5-command(config-manager)' \
        "https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" \
        "https://download1.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm"

    # fedora-multimedia removed in favor of rpmfusion

    dnf -y "do" \
        --action=install \
        gstreamer1-plugins-good \
        gstreamer1-plugins-ugly \
        gstreamer1-plugins-bad-free \
        lame \
        ffmpeg
else
    dnf install -y epel-release
    /usr/bin/crb enable
    dnf config-manager --set-enabled epel
    dnf config-manager --set-enabled crb

    if is_x86_64_v2; then
        echo "no epel-multimedia for x86_64_v2"
        dnf -y install --downloadonly \
            ffmpeg-free \
            @multimedia \
            gstreamer1-plugins-bad-free \
            gstreamer1-plugins-bad-free-libs \
            gstreamer1-plugins-good \
            gstreamer1-plugins-base \
            lame \
            lame-libs \
            libjxl
    else
        dnf install -y --nogpgcheck https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-${MAJOR_VERSION_NUMBER}.noarch.rpm https://mirrors.rpmfusion.org/nonfree/el/rpmfusion-nonfree-release-${MAJOR_VERSION_NUMBER}.noarch.rpm
        dnf -y install --downloadonly \
            ffmpeg \
            @multimedia \
            gstreamer1-plugins-bad-free \
            gstreamer1-plugins-bad-free-libs \
            gstreamer1-plugins-good \
            gstreamer1-plugins-base \
            lame \
            lame-libs \
            libjxl
    fi
fi

if [[ $IS_ALMALINUX == true ]] && [ "$MAJOR_VERSION_NUMBER" -ge 9 ]; then
    dnf swap -y coreutils-single coreutils
fi

if [[ $IS_FEDORA == false ]] && [ "$MAJOR_VERSION_NUMBER" -ge 10 ]; then
    dnf -y copr enable ublue-os/packages
    dnf config-manager --set-enabled --setopt "copr:copr.fedorainfracloud.org:ublue-os:packages.priority=10"
fi

dnf -y upgrade glib2
dnf versionlock add glib2

if [[ $IS_FEDORA == true ]]; then
    dnf -y group install "kde-desktop"
    dnf -y install --downloadonly \
        -x PackageKit \
        -x PackageKit-command-not-found \
        sddm \
        dolphin \
        konsole \
        kate \
        ark \
        plasma-discover \
        kde-connect \
        xdg-desktop-portal \
        xdg-desktop-portal-kde \
        qt5-qtwayland \
        qt6-qtwayland \
        plymouth \
        plymouth-system-theme \
        fwupd \
        systemd-resolved \
        systemd-container \
        systemd-oomd-defaults \
        distrobox \
        fastfetch \
        fpaste \
        buildah \
        podman \
        skopeo \
        btrfs-progs
else
    dnf group install -y --downloadonly --nobest \
        "KDE Plasma Workspaces" \
        "Common NetworkManager submodules" \
        "Core" \
        "Fonts" \
        "Guest Desktop Agents" \
        "Hardware Support" \
        "Printing Client" \
        "Standard"

    dnf -y install --downloadonly \
        -x PackageKit \
        -x PackageKit-command-not-found \
        sddm \
        dolphin \
        konsole \
        kate \
        ark \
        plasma-discover \
        kde-connect \
        xdg-desktop-portal \
        xdg-desktop-portal-kde \
        qt5-qtwayland \
        qt6-qtwayland \
        plymouth \
        plymouth-system-theme \
        fwupd \
        systemd-resolved \
        systemd-container \
        systemd-oomd \
        libcamera-v4l2 \
        libcamera-gstreamer \
        libcamera-tools \
        system-reinstall-bootc \
        distrobox \
        fastfetch \
        fpaste \
        powertop \
        tuned-ppd \
        fzf \
        glow \
        wl-clipboard \
        gum \
        buildah \
        btrfs-progs \
        xhost
fi

dnf -y remove console-login-helper-messages setroubleshoot

printf "::endgroup::\n"
