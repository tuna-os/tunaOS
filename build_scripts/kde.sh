#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	# ublue-os/packages COPR dropped EPEL/CentOS chroots; only Fedora remains.
	# The install_available --copr calls below handle enabling per-package on Fedora.
	if [[ $IS_FEDORA == false ]] && [ "$MAJOR_VERSION_NUMBER" -ge 10 ]; then
		warn_on_fail dnf -y copr enable ublue-os/packages
		warn_on_fail dnf config-manager --set-enabled --setopt "copr:copr.fedorainfracloud.org:ublue-os:packages.priority=10"
	fi

	if [[ $IS_FEDORA == true ]]; then
		dnf -y group install "kde-desktop"
		# Fedora-only set: these are Aurora's KDE package selection
		# (ublue-os/aurora build_files/base/01-packages.sh FEDORA_PACKAGES).
		# All available in Fedora repos; safe to install in one transaction.
		dnf_retry -y install \
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
			qt6-qtwayland \
			ksshaskpass \
			ksystemlog \
			input-remapper \
			evtest \
			tesseract \
			libratbag-ratbagd \
			solaar-udev \
			openrgb-udev-rules \
			pam-u2f \
			pam_yubico \
			pamu2fcfg \
			yubikey-manager \
			nvtop
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

		dnf_retry -y install \
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
			qt6-qtwayland

		# EL10 catch-up to Aurora's Fedora-only package set. lib.sh's
		# install_available probes each one against the active repos
		# (BaseOS / AppStream / EPEL10 / CRB + the ublue-os/packages
		# COPR for things like `kcm_ublue`) and installs only what
		# resolves. Misses get logged so the next porter sees the gap.
		install_available --copr ublue-os/packages \
			ksshaskpass \
			ksystemlog \
			input-remapper \
			evtest \
			tesseract \
			libratbag-ratbagd \
			solaar-udev \
			openrgb-udev-rules \
			pam-u2f \
			pam_yubico \
			pamu2fcfg \
			yubikey-manager \
			nvtop \
			kcm_ublue

		# Install fcitx5 input method support (Asian languages) if available
		# Not available in EPEL10 yet
		if dnf repoquery --available fcitx5 2>/dev/null | grep -q .; then
			dnf_retry -y install \
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
		else
			echo "Skipping fcitx5 packages (not available in repos)"
		fi

		# Version lock critical KDE packages to prevent partial upgrades causing black screens
		# Reference: https://github.com/ublue-os/aurora/issues/1227
		dnf_retry -y install python3-dnf-plugin-versionlock
		dnf versionlock add plasma-desktop
		dnf versionlock add "qt6-*"
	fi
	;;
"extra")
	# ublue-os packages — most moved to the common OCI layer; only KDE-
	# specific extras stay here. install_available probes each name in
	# the COPR so a missing entry (e.g. krunner-bazaar awaiting Qt 6.10
	# on EL10) is logged-and-skipped rather than aborting the build.
	# Reference: https://github.com/ublue-os/aurora/issues/1227
	install_available --copr ublue-os/packages \
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
