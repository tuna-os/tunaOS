#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
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
			xdg-desktop-portal-kde \
			qt5-qtwayland \
			qt6-qtwayland
	else
		dnf group install -y --nobest \
			-x plasma-discover \
			-x plasma-discover-notifier \
			-x plasma-nm-vpnc \
			-x pinentry-qt \
			-x plasma-workspace-wayland \
			-x plasma-workspace-geolocation \
			-x plasma-drkonqi \
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
			kde-connect \
			xdg-desktop-portal-kde \
			qt5-qtwayland \
			qt6-qtwayland \
			plasma-wallpapers-dynamic

		# Install fcitx5 input method support (Asian languages)
		dnf -y install \
			fcitx5 \
			fcitx5-chewing \
			fcitx5-chinese-addons \
			fcitx5-gtk \
			fcitx5-hangul \
			fcitx5-m17n \
			fcitx5-mozc \
			fcitx5-qt \
			fcitx5-sayura \
			fcitx5-unikey \
			kcm-fcitx5

		# Version lock critical KDE packages to prevent partial upgrades causing black screens
		# Reference: https://github.com/ublue-os/aurora/issues/1227
		dnf -y install python3-dnf-plugin-versionlock
		dnf versionlock add plasma-desktop
		dnf versionlock add "qt6-*"
	fi
	;;
"extra")
	# ublue-os packages - most packages moved to common OCI, only KDE-specific remain
	dnf -y copr enable ublue-os/packages
	dnf -y copr disable ublue-os/packages
	dnf -y --enablerepo copr:copr.fedorainfracloud.org:ublue-os:packages install \
		kcm_ublue \
		krunner-bazaar

	# Disable plasma-discover in favor of Flatpak/Bazaar (like Aurora)
	if [ -f /usr/share/applications/org.kde.discover.desktop ]; then
		mv /usr/share/applications/org.kde.discover.desktop \
			/usr/share/applications/org.kde.discover.desktop.disabled
	fi
	if [ -f /usr/share/applications/org.kde.discover.urlhandler.desktop ]; then
		mv /usr/share/applications/org.kde.discover.urlhandler.desktop \
			/usr/share/applications/org.kde.discover.urlhandler.desktop.disabled
	fi
	;;
esac
