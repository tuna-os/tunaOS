#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

if [[ $IS_FEDORA == false ]] && [ "$MAJOR_VERSION_NUMBER" -ge 10 ]; then
	dnf -y copr enable ublue-os/packages
	dnf config-manager --set-enabled --setopt "copr:copr.fedorainfracloud.org:ublue-os:packages.priority=10"
fi

if [[ $IS_FEDORA == true ]]; then
	dnf -y group install "kde-desktop"
	dnf -y install \
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
	dnf group install -y --nobest \
		"KDE Plasma Workspaces" \
		"Common NetworkManager submodules" \
		"Core" \
		"Fonts" \
		"Guest Desktop Agents" \
		"Hardware Support" \
		"Printing Client" \
		"Standard"

	dnf -y install \
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
