#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	# ── apt (Ubuntu/Debian) Niri path ──────────────────────────────────
	if [[ "$PKG_MGR" == "apt" ]]; then
		# AvengeMedia publishes the supported Niri + DMS stack for Ubuntu
		# 25.10+ (the same upstream desktop stack Zirconium consumes). Ubuntu
		# itself provides greetd. `greetd-spawn` is an RPM-only package name;
		# its PAM file is supplied by the Zirconium context in Containerfile.ubuntu.
		# Keep the PPA key scoped to these two repositories rather than trusting
		# it globally.
		. /etc/os-release
		# TunaOS branding replaces VERSION_CODENAME with the variant's fish
		# codename. UBUNTU_CODENAME deliberately retains the actual Launchpad
		# suite (for example, resolute) and must drive PPA source entries.
		codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:?Ubuntu codename is required}}"
		install -d -m 0755 /etc/apt/keyrings
		curl -fsSL \
			'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x45FECBE587307AAA3F0A4BE9FC44813D2A7788B7' |
			gpg --dearmor --yes -o /etc/apt/keyrings/avengemedia.gpg
		cat >/etc/apt/sources.list.d/avengemedia.sources <<EOF
Types: deb
URIs: https://ppa.launchpadcontent.net/avengemedia/danklinux/ubuntu
Suites: ${codename}
Components: main
Signed-By: /etc/apt/keyrings/avengemedia.gpg

Types: deb
URIs: https://ppa.launchpadcontent.net/avengemedia/dms/ubuntu
Suites: ${codename}
Components: main
Signed-By: /etc/apt/keyrings/avengemedia.gpg
EOF
		apt-get update -qq
		pkg_install niri greetd quickshell dms dms-greeter

		# Install Niri ecosystem packages (mirrors the Fedora/EL10 set where
		# Ubuntu packages exist — excludes Fedora/COPR-only packages like
		# iio-niri and valent-git.)
		if apt-cache show brightnessctl &>/dev/null 2>&1; then
			pkg_install \
				brightnessctl \
				btop \
				cava \
				ddcutil \
				fastfetch \
				fcitx5-rime \
				flatpak \
				foot \
				fzf \
				gnome-disk-utility \
				gnome-keyring \
				libpam-gnome-keyring \
				just \
				khal \
				nautilus \
				python3-nautilus \
				ssh-askpass-gnome \
				pipewire \
				playerctl \
				udiskie \
				wl-clipboard \
				wl-mirror \
				wtype \
				xdg-desktop-portal-gtk \
				xdg-desktop-portal-gnome \
				xdg-terminal-exec \
				xdg-user-dirs \
				xwayland-satellite \
				systemd-zram-generator
		fi

		# Build/install glib schemas (required for dconf/gsettings)
		if command -v glib-compile-schemas &>/dev/null; then
			glib-compile-schemas /usr/share/glib-2.0/schemas
		fi

		# Apply Niri-specific system file overrides from Zirconium
		copy_systemfiles_for niri

		exit 0
	fi
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
		dnf_retry -y install greetd greetd-selinux

		# Install Niri window manager from yalter/niri-git COPR
		dnf -y --enablerepo copr:copr.fedorainfracloud.org:yalter:niri-git install \
			--setopt=install_weak_deps=False \
			niri

		# Verify niri installation
		niri --version | grep -i -E "niri [[:digit:]]*\.[[:digit:]]* (.*\.git\..*)" || true

		# Install DankMaterialShell suite (quickshell-git + dms shell + theming/tools)
		dnf -y copr enable avengemedia/danklinux
		dnf -y copr enable avengemedia/dms-git
		dnf -y --enablerepo copr:copr.fedorainfracloud.org:avengemedia:dms-git \
			--enablerepo copr:copr.fedorainfracloud.org:avengemedia:danklinux install \
			--setopt=install_weak_deps=False \
			quickshell-git \
			dms \
			dms-cli \
			dms-greeter \
			dgop \
			dsearch \
			matugen
		dnf -y copr disable avengemedia/danklinux
		dnf -y copr disable avengemedia/dms-git

		# Install Fedora Niri ecosystem packages from zirconium/packages COPR
		dnf -y --enablerepo copr:copr.fedorainfracloud.org:zirconium:packages install \
			iio-niri \
			valent-git || echo "Skipping iio-niri/valent-git (not available in COPR for this Fedora version)"

		# Install Niri desktop environment packages (Fedora repos)
		FCITX5_MOZC=""
		if dnf repoquery --available fcitx5-mozc &>/dev/null; then
			FCITX5_MOZC="fcitx5-mozc"
		else
			echo "Skipping fcitx5-mozc (not available in repos)"
		fi

		dnf_retry -y install --setopt=install_weak_deps=False \
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
			zram-generator \
			bolt \
			btop \
			fcitx5-rime \
			gst-thumbnailers \
			librime-lua \
			lshw \
			nano-default-editor \
			nm-connection-editor \
			NetworkManager-tui \
			openrgb-udev-rules \
			qt6-qtimageformats \
			tesseract \
			xdg-desktop-portal-gnome \
			xorg-x11-server-Xwayland

		# Install Qt/KDE theming support for visual consistency
		dnf_retry -y install --setopt=install_weak_deps=False \
			kf6-kirigami \
			qt6ct \
			plasma-breeze \
			kf6-qqc2-desktop-style

		# Install fonts
		dnf_retry -y install \
			default-fonts-core-emoji \
			google-noto-color-emoji-fonts \
			google-noto-emoji-fonts \
			glibc-all-langpacks \
			default-fonts

		# Build/install glib schemas
		glib-compile-schemas /usr/share/glib-2.0/schemas || true

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

	dnf -y copr enable ligenix/enterprise-cosmic rhel+epel-10-x86_64
	dnf -y copr disable ligenix/enterprise-cosmic

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
	dnf -y --enablerepo copr:copr.fedorainfracloud.org:yselkowitz:wlroots-epel \
		--enablerepo copr:copr.fedorainfracloud.org:ligenix:enterprise-cosmic \
		install --setopt=install_weak_deps=False \
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

	# Install DankMaterialShell suite (quickshell + dms shell + theming/tools)
	# Only enabled for AlmaLinux Kitten and CentOS Stream 10 (Qt 6.10+)
	# Needs ligenix repo enabled for dms-greeter -> greetd dependency
	if [[ $IS_ALMALINUXKITTEN == true || $IS_CENTOS == true ]]; then
		dnf -y copr enable avengemedia/danklinux
		dnf -y copr enable avengemedia/dms-git
		dnf -y --enablerepo copr:copr.fedorainfracloud.org:avengemedia:dms-git \
			--enablerepo copr:copr.fedorainfracloud.org:avengemedia:danklinux \
			--enablerepo copr:copr.fedorainfracloud.org:ligenix:enterprise-cosmic install \
			--setopt=install_weak_deps=False \
			quickshell \
			dms \
			dms-cli \
			dms-greeter \
			matugen \
			dgop \
			danksearch
		dnf -y copr disable avengemedia/danklinux
		dnf -y copr disable avengemedia/dms-git
	fi

	# Restore brightnessctl and playerctl for compatible EL10 variants (Kitten/CentOS)
	if [[ $IS_ALMALINUXKITTEN == true || $IS_CENTOS == true ]]; then
		install_available --copr ligenix/enterprise-cosmic \
			brightnessctl \
			playerctl
	fi

	# Zirconium-parity extras on EL10 — many of these are Fedora-shipped
	# but show up in EL10 via EPEL / CRB. install_available probes each
	# and skips the rest so a missing EL10 build of, say, librime-lua
	# doesn't kill the whole package install transaction.
	# ublue-os/packages COPR removed — EPEL chroots dropped.
	install_available \
		bolt \
		btop \
		gst-thumbnailers \
		input-remapper \
		librime-lua \
		lshw \
		nano-default-editor \
		nm-connection-editor \
		NetworkManager-tui \
		openrgb-udev-rules \
		qt6-qtimageformats \
		tesseract \
		xdg-desktop-portal-gnome \
		xorg-x11-server-Xwayland \
		fcitx5-rime

	# Attempt to install greetd-selinux separately (handles greetd-selinux conflict)
	# Use --nobest and --allowerasing to resolve EL10 policy conflicts
	dnf_retry -y install --setopt=install_weak_deps=False --nobest --allowerasing \
		greetd-selinux || true

	# Attempt to install GNOME keyring components (may fail if not in repos)
	dnf_retry -y install --setopt=install_weak_deps=False \
		gnome-keyring \
		gnome-keyring-pam || true

	# Install Qt/KDE theming support for better visual consistency
	dnf_retry -y install --setopt=install_weak_deps=False \
		kf6-kirigami \
		qt6ct \
		plasma-breeze \
		kf6-qqc2-desktop-style

	# Install fonts
	dnf_retry -y install \
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
		# These may not be available for all Fedora versions; skip gracefully if absent
		dnf -y copr enable zirconium/packages
		dnf -y copr disable zirconium/packages
		dnf -y --enablerepo copr:copr.fedorainfracloud.org:zirconium:packages install \
			iio-niri \
			valent-git || echo "Skipping iio-niri/valent-git (not available in COPR for this Fedora version)"
	fi
	;;
esac
