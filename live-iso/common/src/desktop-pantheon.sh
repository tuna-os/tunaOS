#!/usr/bin/env bash
# Pantheon (elementary) live-session adapter.
#
# WHY THIS FILE EXISTS: customize-live.sh's desktop detection had no pantheon
# branch, and DESKTOP defaults to "gnome". So a Pantheon image ran
# desktop-gnome.sh, which writes GDM autologin:
#
#   /etc/gdm/custom.conf
#     [daemon]
#     AutomaticLoginEnable=True
#     AutomaticLogin=liveuser
#
# MEASURED on the published gurnard-pantheon ISO: that file is present, and
# the image ships NO gdm at all -- lightdm is the only display manager, and
# /etc/systemd/system/display-manager.service points at lightdm.service. So
# the autologin config landed where nothing reads it, LightDM was never told
# to log anyone in, and the live session never started. The harness saw a
# black screen (stddev=0 on every frame, three runs, 420s settle) and the
# guest ships no sshd to explain itself with.
#
# liveuser DID exist in that ISO. The account was fine; nothing logged it in.
set -exo pipefail

# ── LightDM autologin ───────────────────────────────────────────────────────
# elementary reads /etc/lightdm/lightdm.conf.d/*.conf; the published image
# ships the directory absent, so create it. Numeric prefix so this sorts after
# anything the image itself may add later.
mkdir -p /etc/lightdm/lightdm.conf.d
tee /etc/lightdm/lightdm.conf.d/90-tunaos-live-autologin.conf <<'LIGHTDMEOF'
[Seat:*]
autologin-user=liveuser
autologin-user-timeout=0
autologin-session=pantheon
LIGHTDMEOF

# autologin-session must name a session file that actually exists. The
# published image ships both pantheon.desktop (X11) and
# pantheon-wayland.desktop; prefer Wayland when present, since that is what
# the installed system defaults to, and fall back rather than guessing.
if [[ -f /usr/share/wayland-sessions/pantheon-wayland.desktop ]]; then
	sed -i 's/^autologin-session=.*/autologin-session=pantheon-wayland/' \
		/etc/lightdm/lightdm.conf.d/90-tunaos-live-autologin.conf
elif [[ ! -f /usr/share/xsessions/pantheon.desktop ]]; then
	echo "desktop-pantheon: WARNING no pantheon session file found; leaving autologin-session=pantheon" >&2
fi

# lightdm's autologin needs the user in the autologin group on Debian/Ubuntu
# when pam_group is configured; harmless where it is not.
groupadd -f autologin || true
usermod -aG autologin liveuser || true

# ── Launch the installer at session start ───────────────────────────────────
# Same mechanism the other adapters use: an xdg autostart entry. Pantheon
# honours /etc/xdg/autostart like any other freedesktop session.
mkdir -p /etc/xdg/autostart
tee /etc/xdg/autostart/org.tunaos.installer-live.desktop <<'DESKEOF'
[Desktop Entry]
Type=Application
Name=Install TunaOS
Exec=flatpak run org.bootcinstaller.Installer
X-GNOME-Autostart-enabled=true
NoDisplay=false
DESKEOF

echo "desktop-pantheon: lightdm autologin + installer autostart configured"
