#!/usr/bin/env bash
# XFCE greeter provisioning: the display manager, gtkgreet + cage, the
# wayland-sessions fallback, and the greetd config that points at them.
#
# THIS MUST BE A post_install SCRIPT, not part of desktop/xfce.sh.
# install-desktop.sh sources only the scripts a manifest names
# (install-desktop.sh:655), so everything in desktop/xfce.sh is dead code for
# the manifest-driven flavors. Not a theory: with the theme half moved out in
# #1085, the xfce build reached the NEXT gate and died on
#
#   missing required command: gtkgreet
#
# in run 31224115663 — because `install_available gtkgreet` was still in the
# file that never runs. Two gates, one root cause, the second hidden behind
# the first.
#
# Sourced, not executed: no `exit` here, it would abort the whole desktop
# install. Indentation is carried over verbatim from the original block so
# the heredocs inside stay intact.

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
