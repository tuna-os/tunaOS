#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	if [[ $IS_FEDORA == true ]]; then
		# Fedora ships COSMIC in the main repos
		dnf -y install --setopt=install_weak_deps=False \
			cosmic-session \
			cosmic-comp \
			cosmic-panel \
			cosmic-app-library \
			cosmic-applets \
			cosmic-bg \
			cosmic-files \
			cosmic-idle \
			cosmic-launcher \
			cosmic-notifications \
			cosmic-osd \
			cosmic-randr \
			cosmic-screenshot \
			cosmic-settings \
			cosmic-settings-daemon \
			cosmic-term \
			cosmic-wallpapers \
			cosmic-workspaces \
			cosmic-greeter \
			cosmic-icon-theme \
			greetd \
			xdg-desktop-portal-cosmic \
			pop-gtk-theme \
			pop-icon-theme

		exit 0
	fi

	# EL10 COSMIC build (AlmaLinux Kitten, AlmaLinux 10, CentOS Stream 10)
	# Enable yselkowitz/cosmic-epel COPR
	dnf -y copr enable yselkowitz/cosmic-epel
	dnf -y copr disable yselkowitz/cosmic-epel

	# Install COSMIC desktop from COPR
	dnf -y --enablerepo copr:copr.fedorainfracloud.org:yselkowitz:cosmic-epel \
		install --setopt=install_weak_deps=False \
		cosmic-session \
		cosmic-comp \
		cosmic-panel \
		cosmic-app-library \
		cosmic-applets \
		cosmic-bg \
		cosmic-files \
		cosmic-idle \
		cosmic-launcher \
		cosmic-notifications \
		cosmic-osd \
		cosmic-randr \
		cosmic-screenshot \
		cosmic-settings \
		cosmic-settings-daemon \
		cosmic-term \
		cosmic-wallpapers \
		cosmic-workspaces \
		cosmic-greeter \
		cosmic-icon-theme \
		cosmic-config-fedora \
		greetd \
		xdg-desktop-portal-cosmic \
		pop-gtk-theme \
		pop-icon-theme \
		adw-gtk3-theme

	# Verify cosmic-session installed
	cosmic-session --version || true

	# Install additional desktop utilities
	dnf -y install --setopt=install_weak_deps=False \
		brightnessctl \
		flatpak \
		playerctl \
		pipewire \
		wireplumber \
		wl-clipboard \
		xdg-user-dirs \
		gnome-keyring \
		gnome-keyring-pam \
		zram-generator

	# Build/install glib schemas
	glib-compile-schemas /usr/share/glib-2.0/schemas || true

	# Fix PAM for greetd - enable gnome_keyring for credential storage
	if [ -f /etc/pam.d/greetd ]; then
		sed --sandbox -i -e '/gnome_keyring.so/ s/-auth/auth/ ; /gnome_keyring.so/ s/-session/session/' /etc/pam.d/greetd
	fi

	;;
esac
