#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	# Use COPR GNOME 48 packages for EL10-based builds.
	if [[ $IS_FEDORA == false ]] && [ "$MAJOR_VERSION_NUMBER" -ge 10 ]; then
		dnf -y copr enable jreilly1821/c10s-gnome
		dnf -y swap gnome-shell gnome-shell-48.3 --allowerasing || true
		dnf -y copr disable jreilly1821/c10s-gnome
	fi

	# Install base groups and packages - different between Fedora and RHEL/AlmaLinux
	if [[ $IS_FEDORA == true ]]; then
		# Fedora Silverblue-style package list
		dnf -y install \
			-x PackageKit \
			-x PackageKit-command-not-found \
			-x gnome-software \
			-x gnome-software-fedora-langpacks \
			ModemManager \
			NetworkManager-adsl \
			NetworkManager-openconnect-gnome \
			NetworkManager-openvpn-gnome \
			NetworkManager-ppp \
			NetworkManager-ssh-gnome \
			NetworkManager-vpnc-gnome \
			NetworkManager-wwan \
			avahi \
			dconf \
			fprintd-pam \
			gdm \
			glib-networking \
			gnome-backgrounds \
			gnome-bluetooth \
			gnome-browser-connector \
			gnome-classic-session \
			gnome-color-manager \
			gnome-control-center \
			gnome-disk-utility \
			gnome-initial-setup \
			gnome-remote-desktop \
			gnome-session-wayland-session \
			gnome-settings-daemon \
			gnome-shell \
			gnome-system-monitor \
			gnome-user-docs \
			gnome-user-share \
			gvfs-afc \
			gvfs-afp \
			gvfs-archive \
			gvfs-fuse \
			gvfs-goa \
			gvfs-gphoto2 \
			gvfs-mtp \
			gvfs-smb \
			librsvg2 \
			libsane-hpaio \
			mesa-dri-drivers \
			mesa-libEGL \
			mesa-vulkan-drivers \
			nautilus \
			polkit \
			ptyxis \
			xdg-desktop-portal-gnome \
			xdg-desktop-portal-gtk \
			xdg-user-dirs-gtk \
			yelp \
			desktop-backgrounds-gnome \
			pinentry-gnome3 \
			qadwaitadecorations-qt5 \
			evince-thumbnailer \
			evince-previewer \
			totem-video-thumbnailer
	else
		# RHEL/AlmaLinux base groups
		dnf group install -y --nobest \
			-x PackageKit \
			-x PackageKit-command-not-found \
			"Common NetworkManager submodules" \
			"Core" \
			"Fonts" \
			"Guest Desktop Agents" \
			"Hardware Support" \
			"Printing Client" \
			"Standard" \
			"Workstation product core"

		dnf -y install \
			-x gnome-software \
			-x gnome-extensions-app \
			-x PackageKit \
			-x PackageKit-command-not-found \
			-x gnome-software-fedora-langpacks \
			"NetworkManager-adsl" \
			"glib2" \
			"gdm" \
			"gnome-bluetooth" \
			"gnome-color-manager" \
			"gnome-control-center" \
			"gnome-initial-setup" \
			"gnome-remote-desktop" \
			"gnome-session-wayland-session" \
			"gnome-settings-daemon" \
			"gnome-shell" \
			"gnome-user-docs" \
			"gvfs-fuse" \
			"gvfs-goa" \
			"gvfs-gphoto2" \
			"gvfs-mtp" \
			"gvfs-smb" \
			"libsane-hpaio" \
			"nautilus" \
			orca \
			ptyxis \
			"sane-backends-drivers-scanners" \
			"xdg-desktop-portal-gnome" \
			"xdg-user-dirs-gtk" \
			"yelp-tools" \
			"gnome-disk-utility"
	fi

	# Build GNOME extensions from source (must run after gnome-shell is installed)
	echo "Building GNOME extensions from source..."

	# Install build tooling
	dnf -y install glib2-devel meson sassc cmake dbus-devel unzip

	# AppIndicator Support
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/appindicatorsupport@rgcjonas.gmail.com/schemas

	# Blur My Shell (requires gnome-extensions pack from gnome-shell)
	make -C /usr/share/gnome-shell/extensions/blur-my-shell@aunetx
	unzip -o /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/build/blur-my-shell@aunetx.shell-extension.zip -d /usr/share/gnome-shell/extensions/blur-my-shell@aunetx
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/schemas
	rm -rf /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/build

	# Caffeine
	# The Caffeine extension is built/packaged into a temporary subdirectory (tmp/caffeine/caffeine@patapon.info).
	# Unlike other extensions, it must be moved to the standard extensions directory so GNOME Shell can detect it.
	mv /usr/share/gnome-shell/extensions/tmp/caffeine/caffeine@patapon.info /usr/share/gnome-shell/extensions/caffeine@patapon.info
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/caffeine@patapon.info/schemas

	# Dash to Dock
	make -C /usr/share/gnome-shell/extensions/dash-to-dock@micxgx.gmail.com
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/dash-to-dock@micxgx.gmail.com/schemas

	# GSConnect
	meson setup --prefix=/usr /usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io /usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io/_build
	meson install -C /usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io/_build --skip-subprojects
	# GSConnect installs schemas to /usr/share/glib-2.0/schemas and meson compiles them automatically

	# Logo Menu
	# xdg-terminal-exec is required for this extension as it opens up terminals using that script
	install -Dpm0755 -t /usr/bin /usr/share/gnome-shell/extensions/logomenu@aryan_k/distroshelf-helper
	install -Dpm0755 -t /usr/bin /usr/share/gnome-shell/extensions/logomenu@aryan_k/missioncenter-helper
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/logomenu@aryan_k/schemas

	# Search Light
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/search-light@icedman.github.com/schemas

	# Recompile all schemas
	rm /usr/share/glib-2.0/schemas/gschemas.compiled
	glib-compile-schemas /usr/share/glib-2.0/schemas

	# Cleanup build tooling
	dnf -y remove glib2-devel meson sassc cmake dbus-devel
	rm -rf /usr/share/gnome-shell/extensions/tmp
	;;
"extra")
	# ublue-os packages - most packages moved to common OCI, only uupd remains
	dnf -y copr enable ublue-os/packages
	dnf -y copr disable ublue-os/packages
	dnf -y --enablerepo copr:copr.fedorainfracloud.org:ublue-os:packages install uupd
	;;
esac
