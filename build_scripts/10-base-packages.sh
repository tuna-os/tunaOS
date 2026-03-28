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
	elif [[ $IS_RHEL == true ]]; then
		# Check for subscription-manager credentials and register if present
		if [[ -n "${RHSM_USER:-}" ]] && [[ -n "${RHSM_PASSWORD:-}" ]]; then
			echo "Registering with Red Hat Subscription Manager using credentials..."
			subscription-manager register --username "${RHSM_USER}" --password "${RHSM_PASSWORD}" --auto-attach || true
		elif [[ -n "${RHSM_ORG:-}" ]] && [[ -n "${RHSM_ACTIVATION_KEY:-}" ]]; then
			echo "Registering with Red Hat Subscription Manager using activation key..."
			subscription-manager register --org "${RHSM_ORG}" --activationkey "${RHSM_ACTIVATION_KEY}" --auto-attach || true
		fi

		# Ensure repositories are enabled after registration
		subscription-manager repos --enable "rhel-10-for-x86_64-baseos-rpms" || true
		subscription-manager repos --enable "rhel-10-for-x86_64-appstream-rpms" || true
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
			# Disable fastestmirror for this repo to avoid corrupted mirrors
			dnf config-manager --setopt="epel-multimedia.fastestmirror=0" --save

			# Install with retries to handle transient mirror issues
			retry_count=0
			max_retries=3
			until dnf -y install --enablerepo=epel-multimedia \
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
				ffmpegthumbnailer || [ $retry_count -eq $max_retries ]; do
				retry_count=$((retry_count + 1))
				echo "Multimedia package installation failed, retry $retry_count of $max_retries"
				dnf clean metadata
				sleep 5
			done
		fi

	fi

	if [[ $IS_ALMALINUX == true ]] && [ "$MAJOR_VERSION_NUMBER" -ge 9 ]; then
		dnf swap -y coreutils-single coreutils
	fi

	# Install common desktop packages (shared between GNOME and KDE)
	if [[ $IS_FEDORA == true ]]; then
		dnf -y install \
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
			btrfs-progs \
			plymouth \
			plymouth-plugin-script \
			xdg-desktop-portal \
			systemd-oomd-defaults \
			unzip
	else
		# RHEL/AlmaLinux
		dnf -y install \
			buildah \
			btrfs-progs \
			distrobox \
			fastfetch \
			fpaste \
			fwupd \
			systemd-resolved \
			systemd-container \
			systemd-oomd \
			plymouth \
			plymouth-plugin-script \
			libcamera-v4l2 \
			libcamera-gstreamer \
			libcamera-tools \
			system-reinstall-bootc \
			powertop \
			tuned-ppd \
			fzf \
			glow \
			wl-clipboard \
			gum \
			xhost \
			unzip
	fi

	dnf -y remove console-login-helper-messages setroubleshoot

	dnf -y copr enable ublue-os/packages
	dnf -y copr disable ublue-os/packages
	dnf -y --enablerepo copr:copr.fedorainfracloud.org:ublue-os:packages install \
		uupd

	printf "::endgroup::\n"
}
