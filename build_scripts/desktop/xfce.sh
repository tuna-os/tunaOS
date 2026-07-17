#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

case "${1:-}" in
"base")
	# ── dnf (RPM) XFCE path ──────────────────────────────────────────
	if [[ "$PKG_MGR" == "dnf" ]]; then
		if [[ $IS_FEDORA == true ]]; then
			# repo.tunaos.org currently ships EL10/x86_64 only, so bonito
			# gets stock Fedora XFCE 4.20 (X11). Switch to the
			# hanthor/xfce-wayland stack once a Fedora chroot is published.
			# NOTE: do NOT install the tuna-os.repo file here — its
			# $releasever baseurl 404s on Fedora with
			# skip_if_unavailable=False, breaking every later transaction.
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
			# EL10 (AlmaLinux/CentOS Stream): the hanthor/xfce-wayland port —
			# xfwl4 (Rust/Smithay compositor) plus Wayland-adapted
			# panel/session/xfdesktop/settings/thunar. Packaged from
			# tuna-os/github-copr src/xfce-wayland, served by repo.tunaos.org
			# (EL10 x86_64 only — build-config restricts xfce* platforms).
			# NOTE: the stack is not published yet — the EL10 xfce flavors
			# are commented out in build-config until tuna-os/github-copr#65
			# lands. This branch is the intended install path once it does.
			curl -fsSLo /etc/yum.repos.d/tuna-os.repo \
				https://raw.githubusercontent.com/tuna-os/github-copr/main/contrib/tuna-os.repo

			# xfce4-wayland is the meta package tracking the whole adapted
			# stack (xfwl4, panel, session, xfdesktop, settings, thunar,
			# terminal, plugins…) — install it instead of a hand-rolled list
			# so image contents follow the spec's Requires.
			dnf_retry -y install xfce4-wayland

			# xfwl4 reads xfwm4's themes and refuses to start without them
			# (hanthor/xfwl4 README); the meta package does not require
			# xfwm4, so pull it (plus nice-to-haves) if they resolve.
			install_available \
				xfwm4 \
				xfce4-whiskermenu-plugin \
				thunar-volman \
				thunar-archive-plugin \
				ristretto \
				mousepad \
				xfce4-dict \
				catfish
		fi

		# Display manager: neither branch pulls one in. Probe lightdm first
		# (XFCE's usual DM), fall back to greetd; the enable logic below
		# picks whichever landed.
		install_available \
			lightdm \
			lightdm-gtk-greeter \
			greetd \
			greetd-selinux

		# Session entry: the adapted xfce4-session ships a wayland-sessions
		# desktop file running `startxfce4 --wayland`. Only write a fallback
		# if no packaged Wayland session landed (keeps DMs from showing an
		# empty session list on EL10 if packaging regresses).
		if [[ $IS_FEDORA != true ]] && ! compgen -G "/usr/share/wayland-sessions/*.desktop" >/dev/null; then
			mkdir -p /usr/share/wayland-sessions
			cat >/usr/share/wayland-sessions/xfce-wayland.desktop <<'EOF'
[Desktop Entry]
Name=Xfce Session (Wayland)
Comment=XFCE desktop on Wayland (xfwl4)
Exec=startxfce4 --wayland
Type=Application
DesktopNames=XFCE
EOF
		fi

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
		# xfwl4 (Wayland compositor) is not packaged for Ubuntu; ship the
		# standard X11 XFCE stack with lightdm instead.
		pkg_install \
			xfce4-session \
			xfwm4 \
			xfce4-panel \
			xfdesktop4 \
			xfce4-settings \
			xfce4-terminal \
			xfce4-appfinder \
			xfce4-power-manager \
			xfce4-notifyd \
			xfce4-taskmanager \
			xfce4-screenshooter \
			xfce4-pulseaudio-plugin \
			xfce4-whiskermenu-plugin \
			xfce4-clipman-plugin \
			thunar \
			thunar-volman \
			thunar-archive-plugin \
			mousepad \
			ristretto \
			lightdm \
			lightdm-gtk-greeter \
			xdg-desktop-portal-gtk \
			xdg-user-dirs

		systemctl enable lightdm
		exit 0
	fi
	;;
*)
	echo "Usage: $0 base"
	exit 1
	;;
esac
