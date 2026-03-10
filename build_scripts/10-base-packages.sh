#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 10 Base Packages ===\n"

source /run/context/build_scripts/lib.sh

# This thing slows down downloads A LOT for no reason
if [[ $IS_CENTOS == true ]]; then
	dnf remove -y subscription-manager
fi

dnf -y install 'dnf-command(versionlock)'
dnf versionlock add kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt

if [[ $IS_FEDORA == true ]]; then
	# Install config-manager and RPM Fusion in one transaction
	dnf -y "do" \
		--action=install 'dnf5-command(config-manager)' \
		"https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm" \
		"https://download1.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm"

	# using rpmfusion for multimedia

	# Install multimedia packages and remove unwanted ones in single transaction
	dnf -y "do" \
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
		dnf install -y --nogpgcheck https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-${MAJOR_VERSION_NUMBER}.noarch.rpm https://mirrors.rpmfusion.org/nonfree/el/rpmfusion-nonfree-release-${MAJOR_VERSION_NUMBER}.noarch.rpm
		dnf -y install \
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

dnf -y upgrade glib2
# Please, dont remove this as it will break everything GNOME related
dnf versionlock add glib2

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	/run/context/build_scripts/10-kde-base-packages.sh
else
	/run/context/build_scripts/10-gnome-base-packages.sh
fi

dnf -y remove console-login-helper-messages setroubleshoot

printf "::endgroup::\n"
