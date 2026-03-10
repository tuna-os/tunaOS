#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 10 Base Packages ===\n"

source /run/context/build_scripts/lib.sh

# Function to install DE-agnostic base packages
# This can be called from multi-stage builds to create a shared base layer
install_base_packages_no_de() {
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
		# RHEL requires URL-based EPEL install since epel-release is not in default repos
		if [[ $IS_RHEL == true ]]; then
			dnf install -y "https://dl.fedoraproject.org/pub/epel/epel-release-latest-${MAJOR_VERSION_NUMBER}.noarch.rpm"
			subscription-manager repos --enable "codeready-builder-for-rhel-${MAJOR_VERSION_NUMBER}-$(uname -m)-rpms"
		else
			dnf install -y epel-release
			/usr/bin/crb enable
		fi
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
			# Use negativo17 epel-multimedia repo (same as upstream bluefin-lts)
			dnf config-manager --add-repo=https://negativo17.org/repos/epel-multimedia.repo
			dnf config-manager --set-disabled epel-multimedia
			dnf -y install --enablerepo=epel-multimedia \
				ffmpeg \
				libavcodec \
				@multimedia \
				gstreamer1-plugins-bad-free \
				gstreamer1-plugins-bad-free-libs \
				gstreamer1-plugins-good \
				gstreamer1-plugins-base \
				lame \
				lame-libs \
				libjxl \
				ffmpegthumbnailer
		fi

	fi

	if [[ $IS_ALMALINUX == true ]] && [ "$MAJOR_VERSION_NUMBER" -ge 9 ]; then
		dnf swap -y coreutils-single coreutils
	fi

	dnf -y remove console-login-helper-messages setroubleshoot
}

# Main execution: install base packages and DE
install_base_packages_no_de

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	/run/context/build_scripts/kde.sh base
else
	/run/context/build_scripts/gnome.sh base
fi

# Please, dont remove this as it will break everything GNOME related
dnf versionlock add glib2

printf "::endgroup::\n"