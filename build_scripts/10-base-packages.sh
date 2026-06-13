#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 10 Base Packages ===\n"

source /run/context/build_scripts/lib.sh

# Function to install DE-agnostic base packages
# This can be called from multi-stage builds to create a shared base layer
install_base_packages_no_de() {
	# Source RHSM credentials from the BuildKit secret if it's mounted.
	# /run/secrets/rhsm is provided by the `--mount=type=secret,id=rhsm`
	# directive in the Containerfile (only when RHSM_* env was set when
	# the Justfile invoked podman build). The file exports RHSM_USER etc.
	# into our shell so the subscription-manager calls below see them; the
	# secret is gone the moment this RUN completes — no image layer or
	# build-history record retains the values.
	if [[ -f /run/secrets/rhsm ]]; then
		# shellcheck disable=SC1091 # path only exists at build time
		. /run/secrets/rhsm
	fi

	# ── apt (Ubuntu/Debian) path ──────────────────────────────────────────
	if [[ "$PKG_MGR" == "apt" ]]; then
		# Base packages common to all desktop flavors on apt-based systems.
		# Package name mapping from RPM: gcc-c++ → g++, xhost → x11-xserver-utils,
		# systemd-oomd-defaults → systemd-oomd, tuned-ppd → power-profiles-daemon.
		pkg_install \
			buildah \
			podman \
			skopeo \
			systemd-container \
			flatpak \
			distrobox \
			fastfetch \
			pastebinit \
			fwupd \
			systemd-resolved \
			btrfs-progs \
			gcc \
			g++ \
			plymouth \
			plymouth-themes \
			xdg-desktop-portal \
			systemd-oomd \
			power-profiles-daemon \
			fzf \
			glow \
			wl-clipboard \
			gum \
			x11-xserver-utils \
			unzip \
			powertop

		# Remove unwanted packages
		[[ "$IS_UBUNTU" == true ]] && pkg_remove ubuntu-advantage-tools || true

		# Install uupd from GitHub release (same source as RPM path)
		UUPD_VERSION=$(grep '^\s*uupd:' /run/context/image-versions.yaml | sed 's/.*"\(.*\)".*/\1/')
		curl -fsSL "https://github.com/ublue-os/uupd/releases/download/${UUPD_VERSION}/uupd_Linux_$(uname -m | sed 's/x86_64/x86_64/;s/aarch64/arm64/').tar.gz" \
			| tar -xzf - -C /usr/bin uupd
		UUPD_SRC_BASE="https://raw.githubusercontent.com/ublue-os/uupd/${UUPD_VERSION}"
		curl -fsSLo /usr/lib/systemd/system/uupd.service "${UUPD_SRC_BASE}/uupd.service"
		curl -fsSLo /usr/lib/systemd/system/uupd.timer "${UUPD_SRC_BASE}/uupd.timer"
		curl -fsSLo /usr/lib/systemd/system/uupd-manual.service "${UUPD_SRC_BASE}/uupd-manual.service"

		printf "::endgroup::\n"
		return 0
	fi
	# ── dnf (RPM) path continues below ────────────────────────────────────

	# This thing slows down downloads A LOT for no reason
	if [[ $IS_CENTOS == true ]]; then
		dnf remove -y subscription-manager
	elif [[ $IS_RHEL == true ]]; then
		# Check for subscription-manager credentials and register if present
		if [[ -n "${RHSM_USER:-}" ]] && [[ -n "${RHSM_PASSWORD:-}" ]]; then
			echo "Registering with Red Hat Subscription Manager using credentials..."
			warn_on_fail subscription-manager register --username "${RHSM_USER}" --password "${RHSM_PASSWORD}" --auto-attach
		elif [[ -n "${RHSM_ORG:-}" ]] && [[ -n "${RHSM_ACTIVATION_KEY:-}" ]]; then
			echo "Registering with Red Hat Subscription Manager using activation key..."
			warn_on_fail subscription-manager register --org "${RHSM_ORG}" --activationkey "${RHSM_ACTIVATION_KEY}" --auto-attach
		fi

		# Ensure repositories are enabled after registration
		warn_on_fail subscription-manager repos --enable "rhel-10-for-x86_64-baseos-rpms"
		warn_on_fail subscription-manager repos --enable "rhel-10-for-x86_64-appstream-rpms"
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
	# gcc + gcc-c++ are required by Homebrew formulae that build from source
	# (Ported from ublue-os/aurora 844b4865 — feat(packages): Add gcc-c++
	# to packages so Homebrew has a c++).
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
			gcc \
			gcc-c++ \
			plymouth \
			plymouth-system-theme \
			plymouth-plugin-script \
			xdg-desktop-portal \
			systemd-oomd-defaults \
			unzip
	else
		# RHEL/AlmaLinux — wrapped in dnf_retry because this set pulls from EPEL
		# (gum, distrobox, fastfetch, glow). EPEL mirror flakes (curl
		# SSL_ERROR_SYSCALL, partial-file) were the actual cause of albacore CI
		# failures captured in .build-logs/albacore-base.log.
		dnf_retry -y install \
			buildah \
			btrfs-progs \
			distrobox \
			fastfetch \
			fpaste \
			fwupd \
			systemd-resolved \
			systemd-container \
			systemd-oomd \
			gcc \
			gcc-c++ \
			plymouth \
			plymouth-system-theme \
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

	# Install uupd from GitHub release tarball.
	# The ublue-os/packages COPR dropped epel-10 chroots (~2026-06-08);
	# Bluefin LTS adopted this same approach.
	# Version is pinned in image-versions.yaml and tracked by Renovate.
	UUPD_VERSION=$(grep '^\s*uupd:' /run/context/image-versions.yaml | sed 's/.*"\(.*\)".*/\1/')
	curl -fsSL "https://github.com/ublue-os/uupd/releases/download/${UUPD_VERSION}/uupd_Linux_$(uname -m | sed 's/x86_64/x86_64/;s/aarch64/arm64/').tar.gz" \
		| tar -xzf - -C /usr/bin uupd

	# Install systemd units from uupd source (not included in release tarball)
	UUPD_SRC_BASE="https://raw.githubusercontent.com/ublue-os/uupd/${UUPD_VERSION}"
	curl -fsSLo /usr/lib/systemd/system/uupd.service "${UUPD_SRC_BASE}/uupd.service"
	curl -fsSLo /usr/lib/systemd/system/uupd.timer "${UUPD_SRC_BASE}/uupd.timer"
	curl -fsSLo /usr/lib/systemd/system/uupd-manual.service "${UUPD_SRC_BASE}/uupd-manual.service"

	printf "::endgroup::\n"
}
