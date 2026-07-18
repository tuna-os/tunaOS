#!/usr/bin/env bash
# Live ISO desktop adapter: XFCE
# Sourced by live-iso/common/src/build.sh for xfce* desktop flavors.
#
# Configures:
#   - Autologin into the XFCE session (Wayland greetd where available,
#     X11 lightdm/gdm on bases not yet migrated to xfwl4)
#   - Auto-launch the TunaOS installer frontend
#   - Disable suspend/sleep (installer can't recover from S3)

set -euo pipefail

# Wayland-first: EL10 ships the xfwl4 Wayland session (startxfce4 --wayland)
# and greetd — an X11-free stack. Detect it by the packaged Wayland session
# and/or the xfwl4 binary. On bases still on X11 XFCE (Fedora/Debian until
# their xfwl4 packaging lands) fall back to lightdm/gdm autologin.
if compgen -G "/usr/share/wayland-sessions/xfce*.desktop" >/dev/null || command -v xfwl4 &>/dev/null; then
	# ── Wayland (xfwl4) — greetd autologin, no X11 ───────────────────────
	# greetd `command` is run by the user's shell, so it must be the actual
	# exec, not a session-file name. dbus-run-session gives the session a
	# message bus (portals, xfconf) the way a DM login would.
	mkdir -p /etc/greetd
	tee /etc/greetd/config.toml <<'GREETDEOF'
[terminal]
vt = 1

[default_session]
user = "liveuser"
command = "dbus-run-session startxfce4 --wayland"

[initial_session]
user = "liveuser"
command = "dbus-run-session startxfce4 --wayland"
GREETDEOF
	# Enable greetd + boot to graphical.target (server-oriented EL10 bases
	# default to multi-user.target, which would land on a console — same
	# root cause as tunaOS#678 for niri/cosmic).
	systemctl enable greetd.service 2>/dev/null || true
	ln -sf /usr/lib/systemd/system/greetd.service /etc/systemd/system/display-manager.service 2>/dev/null || true
	systemctl set-default graphical.target 2>/dev/null || \
		ln -sf /usr/lib/systemd/system/graphical.target /etc/systemd/system/default.target 2>/dev/null || true
else
	# ── X11 fallback (lightdm, gdm on odd builds) ────────────────────────
	mkdir -p /etc/lightdm/lightdm.conf.d
	tee /etc/lightdm/lightdm.conf.d/50-live-autologin.conf <<'LIGHTDMEOF'
[Seat:*]
autologin-user=liveuser
autologin-user-timeout=0
LIGHTDMEOF
	# lightdm requires the autologin user in the 'autologin' group on deb.
	groupadd -f autologin && usermod -aG autologin liveuser || true

	mkdir -p /etc/gdm
	tee /etc/gdm/custom.conf <<'GDMEOF'
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=liveuser
GDMEOF
fi

# Auto-launch the TunaOS installer frontend in the live session.
# The app is baked into the live squash by customize-live.sh (tacklebox live_customize).
mkdir -p /etc/xdg/autostart
tee /etc/xdg/autostart/org.tunaos.installer-live.desktop <<'DESKEOF'
[Desktop Entry]
Type=Application
Name=Install TunaOS
Exec=flatpak run org.tunaos.InstallerXfce
Icon=org.tunaos.InstallerXfce
OnlyShowIn=XFCE;
DESKEOF

# Disable xfce4-screensaver locking and power suspend for the live session
mkdir -p /etc/xdg/xfce4/xfconf/xfce-perchannel-xml
tee /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-screensaver.xml <<'XFCEOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-screensaver" version="1.0">
  <property name="saver" type="empty">
    <property name="enabled" type="bool" value="false"/>
  </property>
  <property name="lock" type="empty">
    <property name="enabled" type="bool" value="false"/>
  </property>
</channel>
XFCEOF

# Belt-and-braces: mask the systemd sleep targets so the install session
# cannot enter S3 regardless of session power settings.
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target || true
