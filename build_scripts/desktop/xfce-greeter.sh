#!/usr/bin/env bash
# XFCE greeter provisioning: the display manager, gtkgreet + cage, and the
# wayland-sessions fallback. greetd-gtkgreet.sh, listed after this script in
# the xfce manifest, writes the greetd config that points at them.
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

# The greetd config, gtkgreet's session list and its stylesheet come from
# greetd-gtkgreet.sh, the script niri and cosmic use, listed after this one
# in the manifest so the packages above and the session entry are on the
# image when it runs. This file used to write its own copy, which drifted:
# it passed gtkgreet no session list, so on EL10 the "Command to run on
# login" box was empty and a login PAM accepted started nothing (the
# defect tunaOS#4491 fixed for niri). That copy also lacked the shared
# script's greeter-account lookup, VT1 ordering and the software-rendering
# fallback cage needs on a VM without virgl.

# Name the session LightDM opens after a password login. user-session
# defaults to "default", which on a base that also ships GNOME resolves to the
# GNOME session: bonito-xfce (iso-builder run 43187094834) logged the
# GUI-created account into GNOME Shell with "Welcome to Bonito" instead of
# XFCE. Pin the XFCE session file that exists, as the live adapter does for
# autologin-session (live-iso/common/src/desktop-xfce.sh).
# TUNAOS_XFCE_ROOT prefixes the paths for tests/test_xfce_lightdm_user_session.py.
xfce_pin_lightdm_session() {
	local root="${TUNAOS_XFCE_ROOT:-}" name
	for name in xfce xfce4; do
		[[ -f "${root}/usr/share/xsessions/${name}.desktop" ]] || continue
		mkdir -p "${root}/etc/lightdm/lightdm.conf.d"
		printf '[Seat:*]\nuser-session=%s\n' "$name" \
			>"${root}/etc/lightdm/lightdm.conf.d/50-tunaos-xfce-session.conf"
		return 0
	done
	return 0
}

# Enable lightdm or greetd for display management
if command -v lightdm &>/dev/null; then
	xfce_pin_lightdm_session
	systemctl enable lightdm
elif command -v greetd &>/dev/null; then
	systemctl enable greetd
fi
