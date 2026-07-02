#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	# ── dnf (RPM) XFCE Wayland path ──────────────────────────────────
	if [[ "$PKG_MGR" == "dnf" ]]; then
		# Enable the Tuna OS repository for XFCE Wayland packages
		# (xfwl4 compositor, libxfce4windowing, etc. not in EPEL)
		curl -fsSLo /etc/yum.repos.d/tuna-os.repo \
		  https://raw.githubusercontent.com/tuna-os/github-copr/main/contrib/tuna-os.repo

		if [[ $IS_FEDORA == true ]]; then
			# Fedora 44 has XFCE 4.20 in the official repos
			dnf_retry -y group install "xfce-desktop"
			dnf_retry -y install \
				xfce4-terminal \
				xfce4-power-manager \
				xfce4-notifyd \
				xfce4-taskmanager \
				xfce4-screenshooter \
				thunar \
				thunar-volman \
				xfce4-pulseaudio-plugin \
				xfce4-clipman-plugin \
				xfce4-whiskermenu-plugin \
				thunar-archive-plugin \
				ristretto \
				mousepad \
				xfce4-dict \
				catfish
		else
			# EL10 (AlmaLinux/CentOS Stream): install from Tuna OS COPR
			# xfwl4 compositor + XFCE Wayland desktop stack
			dnf_retry -y install \
				xfwl4 \
				xfce4-panel \
				xfce4-session \
				xfdesktop \
				xfce4-settings \
				xfce4-terminal \
				xfce4-power-manager \
				xfce4-notifyd \
				xfce4-taskmanager \
				thunar \
				thunar-volman \
				xfce4-pulseaudio-plugin \
				xfce4-clipman-plugin \
				xfce4-screenshooter \
				xfce4-sensors-plugin \
				xfce4-weather-plugin \
				xfce4-netload-plugin \
				xfce4-cpugraph-plugin \
				xfce4-datetime-plugin \
				xfce4-genmon-plugin \
				xfce4-appfinder
		fi

		# Common post-install: enable xfwl4 as default session
		mkdir -p /usr/share/wayland-sessions
		cat > /usr/share/wayland-sessions/xfwl4.desktop << 'EOF'
[Desktop Entry]
Name=XFCE Wayland (xfwl4)
Comment=XFCE Desktop on Wayland with xfwl4 compositor
Exec=/usr/bin/xfwl4
Type=Application
EOF

		# Enable lightdm or greetd for display management
		if command -v lightdm &>/dev/null; then
			systemctl enable lightdm
		elif command -v greetd &>/dev/null; then
			systemctl enable greetd
		fi

		exit 0
	fi
	# ── apt (Debian/Ubuntu) path ─────────────────────────────────────
	if [[ "$PKG_MGR" == "apt" ]]; then
		echo "XFCE Wayland on Ubuntu not yet implemented"
		exit 0
	fi
	;;
*)
	echo "Usage: $0 base"
	exit 1
	;;
esac
