#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	# Use COPR GNOME packages for EL10-based builds.
	if [[ $IS_FEDORA == false ]] && [ "$MAJOR_VERSION_NUMBER" -ge 10 ]; then
		if [[ "${DESKTOP_FLAVOR:-gnome}" == "gnome50" ]]; then
			GNOME_COPR="jreilly1821/c10s-gnome-50-fresh"
		else
			GNOME_COPR="jreilly1821/c10s-gnome-49"
		fi
		GNOME_REPO_ID="copr:copr.fedorainfracloud.org:$(echo "$GNOME_COPR" | tr '/' ':')"
		dnf -y copr enable "$GNOME_COPR"
		dnf config-manager --save --setopt="${GNOME_REPO_ID}.exclude=glib2*"
		# Use install --allowerasing which is more robust than swap if the package is already present
		dnf -y install gnome-shell --allowerasing || true
		dnf -y copr disable "$GNOME_COPR"
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

	# Remove versionlock on glib2 to allow installing glib2-devel (will re-lock after)
	dnf versionlock delete glib2 || true

	# Install build tooling
	dnf -y install glib2-devel meson sassc cmake dbus-devel unzip

	# AppIndicator Support (not present in all GNOME versions/COPRs)
	if [ -d /usr/share/gnome-shell/extensions/appindicatorsupport@rgcjonas.gmail.com/schemas ]; then
		glib-compile-schemas --strict /usr/share/gnome-shell/extensions/appindicatorsupport@rgcjonas.gmail.com/schemas
	fi

	# Blur My Shell (requires gnome-extensions pack from gnome-shell)
	# We build it and then unzip it into its final location to ensure the structure is correct
	make -C /usr/share/gnome-shell/extensions/blur-my-shell@aunetx build
	unzip -o /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/build/blur-my-shell@aunetx.shell-extension.zip -d /usr/share/gnome-shell/extensions/blur-my-shell@aunetx
	glib-compile-schemas --strict /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/schemas
	rm -rf /usr/share/gnome-shell/extensions/blur-my-shell@aunetx/build

	# Caffeine
	# The Caffeine extension is in system_files/usr/share/gnome-shell/extensions/tmp/caffeine/caffeine@patapon.info
	if [ -d /usr/share/gnome-shell/extensions/tmp/caffeine/caffeine@patapon.info ]; then
		mv /usr/share/gnome-shell/extensions/tmp/caffeine/caffeine@patapon.info /usr/share/gnome-shell/extensions/caffeine@patapon.info
	fi
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
	# Only install if submodule is present
	if [ -f /usr/share/gnome-shell/extensions/logomenu@aryan_k/distroshelf-helper ]; then
		install -Dpm0755 -t /usr/bin /usr/share/gnome-shell/extensions/logomenu@aryan_k/distroshelf-helper
		install -Dpm0755 -t /usr/bin /usr/share/gnome-shell/extensions/logomenu@aryan_k/missioncenter-helper
		glib-compile-schemas --strict /usr/share/gnome-shell/extensions/logomenu@aryan_k/schemas
	else
		echo "Skipping logomenu (submodule not available)"
	fi

	# Search Light
	if [ -d /usr/share/gnome-shell/extensions/search-light@icedman.github.com/schemas ]; then
		glib-compile-schemas --strict /usr/share/gnome-shell/extensions/search-light@icedman.github.com/schemas
	else
		echo "Skipping search-light (submodule not available)"
	fi

	# Recompile all schemas
	rm /usr/share/glib-2.0/schemas/gschemas.compiled
	glib-compile-schemas /usr/share/glib-2.0/schemas

	# Cleanup build tooling
	dnf -y remove glib2-devel meson sassc cmake dbus-devel
	rm -rf /usr/share/gnome-shell/extensions/tmp

	# Re-add versionlock for glib2
	dnf versionlock add glib2
	;;
esac
