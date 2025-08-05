#!/usr/bin/env bash

set -xeuo pipefail

MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

# This is the base for a minimal GNOME system on CentOS Stream.

# This thing slows down downloads A LOT for no reason
# dnf remove -y subscription-manager

# dnf -y install centos-release-hyperscale-kernel
# dnf config-manager --set-disabled "centos-hyperscale,centos-hyperscale-kernel"
# dnf --enablerepo="centos-hyperscale" --enablerepo="centos-hyperscale-kernel" -y update kernel

dnf -y install 'dnf-command(versionlock)'
dnf versionlock add kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt


if [ "${IMAGE_NAME}" != "bonito" ]; then
	dnf install -y epel-release
	dnf config-manager --set-enabled crb
fi

# Multimidia codecs
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



dnf swap -y coreutils-single coreutils

# Gnome 48 Backport
dnf -y copr enable jreilly1821/c10s-gnome-48
dnf -y copr enable jreilly1821/packages


# `dnf group info Workstation` without GNOME
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

# Minimal GNOME group. ("Multimedia" adds most of the packages from the GNOME group. This should clear those up too.)
# In order to reproduce this, get the packages with `dnf group info GNOME`, install them manually with dnf install and see all the packages that are already installed.
# Other than that, I've removed a few packages we didnt want, those being a few GUI applications.
dnf -y install \
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
	"gnome-software" \
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
	"yelp-tools"

dnf -y install \
	plymouth \
	plymouth-system-theme \
	fwupd \
	systemd-resolved \
	systemd-container \
	systemd-oomd \
	libcamera-v4l2 \
	libcamera-gstreamer \
	libcamera-tools

# This package adds "[systemd] Failed Units: *" to the bashrc startup
dnf -y remove console-login-helper-messages
