#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	if [[ $IS_FEDORA == true ]]; then
		# Fedora ships COSMIC in the main repos
		dnf_retry -y install --setopt=install_weak_deps=False \
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
			pop-icon-theme

		exit 0
	fi

	# EL10 COSMIC build (AlmaLinux Kitten, AlmaLinux 10, CentOS Stream 10)
	# Enable yselkowitz/cosmic-epel COPR
	dnf -y copr enable yselkowitz/cosmic-epel
	dnf -y copr disable yselkowitz/cosmic-epel

	# Install COSMIC desktop from COPR (Core components)
	dnf -y --enablerepo copr:copr.fedorainfracloud.org:yselkowitz:cosmic-epel \
		install --setopt=install_weak_deps=False \
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
		cosmic-icon-theme \
		xdg-desktop-portal-cosmic \
		adw-gtk3-theme

	# cosmic-greeter hard-requires fprintd-pam, which CentOS Stream 10 only
	# builds for x86_64 — that gap is why aarch64 cosmic was pinned off in
	# build-config.yml (tunaOS#732). It's now built (tuna-os/github-copr#110,
	# same pinned version as x86_64's 1.94.5) and published at its own R2
	# path, separate from the main tuna-os.repo used above — enable it only
	# on aarch64, only for this one install.
	if [[ "$(uname -m)" == "aarch64" ]]; then
		cat >/etc/yum.repos.d/tuna-os-fprintd.repo <<-'EOF'
		[tuna-os-fprintd]
		name=Tuna OS - fprintd (aarch64)
		baseurl=https://repo.tunaos.org/fprintd/10-stream-aarch64/
		enabled=1
		gpgcheck=0
		gpgkey=https://repo.tunaos.org/public.gpg
		repo_gpgcheck=0
		metadata_expire=3600
		priority=10
		skip_if_unavailable=False
		EOF
	fi

	# Install COSMIC session, greetd and COSMIC greeter separately (handles greetd-selinux conflict)
	# Use --nobest and --allowerasing to resolve EL10 policy conflicts
	dnf -y --enablerepo copr:copr.fedorainfracloud.org:yselkowitz:cosmic-epel \
		install --setopt=install_weak_deps=False --nobest --allowerasing \
		cosmic-session \
		greetd \
		cosmic-greeter || true

	# Verify cosmic-session installed
	cosmic-session --version || true

	# Install additional desktop utilities
	dnf_retry -y install --setopt=install_weak_deps=False \
		flatpak \
		pipewire \
		wireplumber \
		wl-clipboard \
		xdg-user-dirs \
		zram-generator

	# Restore brightnessctl and playerctl for Fedora and compatible EL10 variants (Kitten/CentOS)
	if [[ $IS_FEDORA == true || $IS_ALMALINUXKITTEN == true || $IS_CENTOS == true ]]; then
		dnf_retry -y install --setopt=install_weak_deps=False \
			brightnessctl \
			playerctl || true
	fi

	# Attempt to install GNOME keyring components (may fail if not in repos)
	dnf_retry -y install --setopt=install_weak_deps=False \
		gnome-keyring \
		gnome-keyring-pam || true

	# Build/install glib schemas
	glib-compile-schemas /usr/share/glib-2.0/schemas || true

	# Fix PAM for greetd - enable gnome_keyring for credential storage
	if [ -f /etc/pam.d/greetd ]; then
		sed --sandbox -i -e '/gnome_keyring.so/ s/-auth/auth/ ; /gnome_keyring.so/ s/-session/session/' /etc/pam.d/greetd
	fi

	;;
esac
