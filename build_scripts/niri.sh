#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	# Fedora/EL10 Niri build - handle both variants
	if [[ $IS_FEDORA == true ]]; then
		# Fedora Niri build (from zirconium-dev/zirconium upstream)
		# Enable Fedora-specific COPRs for Niri + DMS ecosystem
		dnf -y copr enable zirconium/packages
		dnf -y copr disable zirconium/packages

		dnf -y copr enable yalter/niri-git
		dnf -y copr disable yalter/niri-git
		dnf -y config-manager setopt copr:copr.fedorainfracloud.org:yalter:niri-git.priority=1

		# Install greetd display manager from Fedora repos (no COPR needed)
		dnf install -y greetd greetd-selinux

		# Install Niri window manager from yalter/niri-git COPR
		dnf -y --enablerepo copr:copr.fedorainfracloud.org:yalter:niri-git install \
			--setopt=install_weak_deps=False \
			niri

		# Verify niri installation
		niri --version | grep -i -E "niri [[:digit:]]*\.[[:digit:]]* (.*\.git\..*)" || true

		# Install Fedora Niri ecosystem packages from zirconium/packages COPR
		dnf -y --enablerepo copr:copr.fedorainfracloud.org:zirconium:packages install \
			iio-niri \
			valent-git


		# Install Niri desktop environment packages (Fedora repos)
		FCITX5_MOZC=""
		if dnf repoquery --available fcitx5-mozc &>/dev/null; then
			FCITX5_MOZC="fcitx5-mozc"
		else
			echo "Skipping fcitx5-mozc (not available in repos)"
		fi

		dnf -y install --setopt=install_weak_deps=False \
			brightnessctl \
			cava \
			chezmoi \
			ddcutil \
			fastfetch \
			${FCITX5_MOZC} \
			flatpak \
			foot \
			fpaste \
			fzf \
			gcr \
			git-core \
			glycin-thumbnailer \
			gnome-disk-utility \
			gnome-keyring \
			gnome-keyring-pam \
			gnupg2-scdaemon \
			hyfetch \
			input-remapper \
			just \
			kf6-kimageformats \
			khal \
			nautilus \
			nautilus-python \
			openssh-askpass \
			orca \
			pipewire \
			playerctl \
			ptyxis \
			qt6-qtmultimedia \
			steam-devices \
			udiskie \
			webp-pixbuf-loader \
			wireplumber \
			wl-clipboard \
			wl-mirror \
			wtype \
			xdg-desktop-portal-gtk \
			xdg-terminal-exec \
			xdg-user-dirs \
			xwayland-satellite \
			ykman \
			zram-generator

		# Install Qt/KDE theming support for visual consistency
		dnf install -y --setopt=install_weak_deps=False \
			kf6-kirigami \
			qt6ct \
			plasma-breeze \
			kf6-qqc2-desktop-style

		# Install fonts
		dnf install -y \
			default-fonts-core-emoji \
			google-noto-color-emoji-fonts \
			google-noto-emoji-fonts \
			glibc-all-langpacks \
			default-fonts

		# Build/install glib schemas
		glib-compile-schemas /usr/share/glib-2.0/schemas || true

		# Install PAM files for DMS greeter
		mkdir -p /usr/lib/pam.d/
		install -Dpm0644 -t /usr/lib/pam.d/ /usr/share/quickshell/dms/assets/pam/* || true

		# Fix PAM for greetd
		if [ -f /etc/pam.d/greetd ]; then
			sed --sandbox -i -e '/gnome_keyring.so/ s/-auth/auth/ ; /gnome_keyring.so/ s/-session/session/' /etc/pam.d/greetd
		fi

		# Remove heavy docs to save space
		rm -rf /usr/share/doc/niri || true
		rm -rf /usr/share/doc/just || true

		# Apply Niri-specific system file overrides (e.g. SELinux permissive config)
		copy_systemfiles_for niri

		exit 0
	fi
	# EL10 Niri build (AlmaLinux Kitten, AlmaLinux 10, CentOS Stream 10)
	# Enable required EL10-specific COPR repositories
	dnf -y copr enable yalter/niri-git
	dnf -y copr disable yalter/niri-git

	dnf -y copr enable yselkowitz/wlroots-epel
	dnf -y copr disable yselkowitz/wlroots-epel

	# Install Niri window manager from yalter/niri-git COPR.
	# libinput must come from yselkowitz/wlroots-epel — the EL10 stock version
	# is too old and doesn't provide the symbols niri requires.
	dnf -y --enablerepo copr:copr.fedorainfracloud.org:yalter:niri-git \
		--enablerepo copr:copr.fedorainfracloud.org:yselkowitz:wlroots-epel install \
		--setopt=install_weak_deps=False \
		libinput \
		niri

	# Verify niri installation
	/usr/bin/niri --version | grep -i -E "niri [[:digit:]]*\.[[:digit:]]* " || true

	# Install Niri desktop environment packages
	dnf -y --enablerepo copr:copr.fedorainfracloud.org:yselkowitz:wlroots-epel install --setopt=install_weak_deps=False \
		chezmoi \
		ddcutil \
		fastfetch \
		flatpak \
		ptyxis \
		fpaste \
		fzf \
		zram-generator \
		git-core \
		gnome-disk-utility \
		gnome-keyring \
		gnome-keyring-pam \
		greetd \
		just \
		nautilus \
		nautilus-python \
		openssh-askpass \
		orca \
		pipewire \
		qt6-qtmultimedia \
		steam-devices \
		webp-pixbuf-loader \
		wireplumber \
		wl-clipboard \
		xdg-desktop-portal-gtk \
		xdg-terminal-exec \
		xdg-user-dirs \
		xwayland-satellite \
		wtype \
		wl-mirror

	# Attempt to install greetd-selinux separately (handles greetd-selinux conflict)
	# Use --nobest and --allowerasing to resolve EL10 policy conflicts
	dnf -y install --setopt=install_weak_deps=False --nobest --allowerasing \
		greetd-selinux || true

	# Attempt to install GNOME keyring components (may fail if not in repos)
	dnf -y install --setopt=install_weak_deps=False \
		gnome-keyring \
		gnome-keyring-pam || true

	# Install Qt/KDE theming support for better visual consistency
	dnf install -y --setopt=install_weak_deps=False \
		kf6-kirigami \
		qt6ct \
		plasma-breeze \
		kf6-qqc2-desktop-style

	# Install fonts
	dnf install -y \
		default-fonts-core-emoji \
		google-noto-color-emoji-fonts \
		google-noto-emoji-fonts \
		glibc-all-langpacks \
		default-fonts

	# Build/install glib schemas (required for dconf/gsettings)
	glib-compile-schemas /usr/share/glib-2.0/schemas || true

	# Fix PAM for greetd - enable gnome_keyring for credential storage
	if [ -f /etc/pam.d/greetd ]; then
		sed --sandbox -i -e '/gnome_keyring.so/ s/-auth/auth/ ; /gnome_keyring.so/ s/-session/session/' /etc/pam.d/greetd
	fi

	# Configure firewall for desktop use
	dnf config-manager --set-enabled crb

	# Remove heavy docs to save space (mirroring gnome.sh pattern)
	rm -rf /usr/share/doc/niri || true
	rm -rf /usr/share/doc/just || true

	# Apply Niri-specific system file overrides (e.g. SELinux permissive config)
	copy_systemfiles_for niri

	;;
"extra")
	if [[ $IS_FEDORA == true ]]; then
		# Fedora: install iio-niri and valent-git from zirconium/packages COPR
		dnf -y copr enable zirconium/packages
		dnf -y copr disable zirconium/packages
		dnf -y --enablerepo copr:copr.fedorainfracloud.org:zirconium:packages install \
			iio-niri \
			valent-git
	fi
	;;
esac
