#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	if [[ $IS_FEDORA == false ]] && [ "$MAJOR_VERSION_NUMBER" -ge 10 ]; then
		if is_x86_64_v2;
			then
			dnf -y copr enable jreilly1821/a10-gnome-x86-v2 alma-kitten+epel-10-x86_64_v2
			# Set high priority for GNOME COPR to override OS packages
			dnf config-manager --set-enabled --setopt "copr:copr.fedorainfracloud.org:jreilly1821:a10-gnome-x86-v2.priority=10"
		else
			dnf -y copr enable jreilly1821/c10s-gnome
			# Set high priority for GNOME COPR to override OS packages
			dnf config-manager --set-enabled --setopt "copr:copr.fedorainfracloud.org:jreilly1821:c10s-gnome.priority=10"
		fi
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
			plymouth \
			plymouth-system-theme \
			polkit \
			ptyxis \
			systemd-oomd-defaults \
			xdg-desktop-portal \
			xdg-desktop-portal-gnome \
			xdg-desktop-portal-gtk \
			xdg-user-dirs-gtk \
			yelp \
			desktop-backgrounds-gnome \
			gnome-shell-extension-background-logo \
			pinentry-gnome3 \
			qadwaitadecorations-qt5 \
			evince-thumbnailer \
			evince-previewer \
			totem-video-thumbnailer \
			buildah \
			podman \
			skopeo \
			systemd-container \
			flatpak \
			distrobox \
			fastfetch \
			fpaste \
			fwupd \
			systemd-resolved \
			btrfs-progs
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
			"plymouth" \
			"plymouth-system-theme" \
			"fwupd" \
			"systemd-resolved" \
			"systemd-container" \
			"systemd-oomd" \
			"libcamera-v4l2" \
			"libcamera-gstreamer" \
			"libcamera-tools" \
			"system-reinstall-bootc" \
			"gnome-disk-utility" \
			"distrobox" \
			"fastfetch" \
			"fpaste" \
			"gnome-shell-extension-appindicator" \
			"gnome-shell-extension-dash-to-dock" \
			"gnome-shell-extension-blur-my-shell" \
			"powertop" \
			"tuned-ppd" \
			"fzf" \
			"glow" \
			"wl-clipboard" \
			"gum" \
			"buildah" \
			"btrfs-progs" \
			"xhost"
	fi
	;;
"extra")
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
		uupd

	# GNOME version specific workarounds
	GNOME_VERSION=$(gnome-shell --version | cut -d ' ' -f 3 | cut -d '.' -f 1 || echo 0)
	if [ "$GNOME_VERSION" -ge 48 ]; then
		# GNOME 48: EPEL version of blur-my-shell is incompatible
		dnf -y remove gnome-shell-extension-blur-my-shell || true
		dnf -y install https://kojipkgs.fedoraproject.org//packages/gnome-shell-extension-blur-my-shell/69/1.fc43/noarch/gnome-shell-extension-blur-my-shell-69-1.fc43.noarch.rpm
	fi
	;;
esac
