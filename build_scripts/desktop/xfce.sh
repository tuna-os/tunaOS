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

		# greetd ships no graphical greeter: its stock config runs
		# `agreety --cmd /bin/sh`, i.e. a text prompt into a bare shell with
		# no session picker. cosmic/niri never hit this because
		# cosmic-greeter/dms-greeter ship their own config.toml — XFCE has no
		# such package, so without this block an installed XFCE system boots
		# to a shell. It still reaches graphical.target with
		# display-manager.service active, so the desktop-contract gate cannot
		# see the difference; only this config can.
		#
		# gtkgreet is GTK3 like the XFCE session, so it inherits the same
		# GTK/icon/cursor/font theme — greeter and desktop match by
		# construction. It pulls cage (its kiosk host) via Requires.
		install_available gtkgreet

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

		# Point greetd at gtkgreet. Only rewrite the config when gtkgreet
		# actually landed — if packaging regressed, leaving greetd's own
		# config in place fails loudly at a text prompt rather than silently
		# launching a greeter that is not installed.
		if command -v gtkgreet &>/dev/null && command -v cage &>/dev/null; then
			# gtkgreet is a plain Wayland client and cannot own a VT, so cage
			# hosts it. -s keeps VT switching available (without it a greeter
			# crash locks you out of the machine entirely).
			mkdir -p /etc/greetd
			cat >/etc/greetd/config.toml <<'EOF'
[terminal]
vt = 1

[default_session]
command = "cage -s -- gtkgreet -l -s /etc/greetd/gtkgreet.css"
user = "greetd"
EOF

			# Greeter styling. Kept deliberately small: gtkgreet is GTK3, so
			# it already picks up the session's GTK theme, icons, cursor and
			# font — this only supplies the pieces a theme cannot know about
			# (the layer-shell background behind the login window).
			cat >/etc/greetd/gtkgreet.css <<'EOF'
/* TunaOS XFCE greeter.
 *
 * gtkgreet inherits the system GTK3 theme, which is the whole reason it is
 * the XFCE greeter: the login screen and the session it launches are styled
 * by the same theme. Only the layer-shell background and the login window's
 * framing are set here — everything else is intentionally left to the theme
 * so retheming the desktop retheme the greeter too.
 */
window {
	background-image: linear-gradient(to bottom, #2b3d4f, #1b2733);
	background-color: #1b2733;
}

/* The login box: lift it off the background, otherwise the themed widgets
 * float on the gradient with no visual container. */
box#window-box {
	background-color: @theme_bg_color;
	border-radius: 8px;
	padding: 24px;
}
EOF
			# greetd runs the greeter as its own unprivileged user; it must be
			# able to read both files.
			chmod 0644 /etc/greetd/config.toml /etc/greetd/gtkgreet.css
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
