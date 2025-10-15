#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 10 Base Packages ===\n"

source /run/context/build_scripts/lib.sh

# This is the base for a minimal GNOME system on CentOS Stream.

# This thing slows down downloads A LOT for no reason
if [[ $IS_CENTOS == true ]]; then
	dnf remove -y subscription-manager
fi
# dnf -y install centos-release-hyperscale-kernel
# dnf config-manager --set-disabled "centos-hyperscale,centos-hyperscale-kernel"
# dnf --enablerepo="centos-hyperscale" --enablerepo="centos-hyperscale-kernel" -y update kernel

dnf -y install 'dnf-command(versionlock)'
dnf versionlock add kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt

if [[ $IS_FEDORA == true ]]; then
	# Install config-manager and RPM Fusion in one transaction
	dnf -y do \
		--action=install 'dnf5-command(config-manager)' \
		"https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" \
		"https://download1.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm"
	
	# Add fedora-multimedia repo and set priority
	dnf config-manager setopt fedora-multimedia.enabled=1 ||
		dnf config-manager addrepo --from-repofile="https://negativo17.org/repos/fedora-multimedia.repo"
	dnf config-manager setopt fedora-multimedia.priority=90
	
	# Install multimedia packages and remove unwanted ones in single transaction
	dnf -y do \
		--action=install \
		gstreamer1-plugins-good \
		gstreamer1-plugins-ugly \
		gstreamer1-plugins-bad-free \
		lame \
		ffmpeg
else
	# Enable the EPEL repos for RHEL and AlmaLinux
	dnf install -y epel-release
	/usr/bin/crb enable
	dnf config-manager --set-enabled epel
	dnf config-manager --set-enabled crb

	# Multimedia codecs
	if is_x86_64_v2; then
		echo "no epel-multimedia for x86_64_v2"
		dnf -y install \
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
		dnf config-manager --add-repo=https://negativo17.org/repos/epel-multimedia.repo
		dnf -y install \
			ffmpeg \
			libavcodec \
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
	if is_x86_64_v2; then
		dnf -y copr enable jreilly1821/a10-gnome-x86-v2 alma-kitten+epel-10-x86_64_v2
		# Set high priority for GNOME COPR to override OS packages
		dnf config-manager --set-enabled --setopt "copr:copr.fedorainfracloud.org:jreilly1821:a10-gnome-x86-v2.priority=10"
	else
		dnf -y copr enable jreilly1821/c10s-gnome
		# Set high priority for GNOME COPR to override OS packages
		dnf config-manager --set-enabled --setopt "copr:copr.fedorainfracloud.org:jreilly1821:c10s-gnome.priority=10"
	fi
fi

dnf -y upgrade glib2
# Please, dont remove this as it will break everything GNOME related
dnf versionlock add glib2

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
		"orca" \
		"ptyxis" \
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

dnf -y remove console-login-helper-messages setroubleshoot

printf "::endgroup::\n"
