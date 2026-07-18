#!/usr/bin/env bash
# Live ISO desktop adapter: XFCE
# Sourced by live-iso/common/src/build.sh for xfce* desktop flavors.
#
# Configures:
#   - GDM autologin to the XFCE session
#   - Auto-launch the TunaOS installer frontend
#   - Disable suspend/sleep (installer can't recover from S3)

set -euo pipefail

# XFCE's display manager varies: lightdm (deb/EL10-x11), greetd (EL10
# wayland fallback), gdm on odd builds. Configure all three; only the
# active one reads its file.
mkdir -p /etc/lightdm/lightdm.conf.d
tee /etc/lightdm/lightdm.conf.d/50-live-autologin.conf <<'LIGHTDMEOF'
[Seat:*]
autologin-user=liveuser
autologin-user-timeout=0
LIGHTDMEOF
# lightdm requires the autologin user in the 'autologin' group on deb.
groupadd -f autologin && usermod -aG autologin liveuser || true

_xfce_session="startxfce4"
compgen -G "/usr/share/wayland-sessions/xfce*.desktop" >/dev/null && _xfce_session="xfce-wayland-session"
mkdir -p /etc/greetd
tee /etc/greetd/config.toml <<GREETDEOF
[terminal]
vt = 1

[default_session]
user = "liveuser"
command = "${_xfce_session}"

[initial_session]
user = "liveuser"
command = "${_xfce_session}"
GREETDEOF

mkdir -p /etc/gdm
tee /etc/gdm/custom.conf <<'GDMEOF'
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=liveuser
GDMEOF

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
