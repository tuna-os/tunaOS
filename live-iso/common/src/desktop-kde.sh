#!/usr/bin/env bash
# Live ISO desktop adapter: KDE Plasma
# Sourced by live-iso/common/src/build.sh for kde* desktop flavors.
#
# Configures:
#   - SDDM autologin to Plasma session (Wayland, no lockscreen)
#   - Disable screen lock + power suspend
#   - Mask suspend targets (installer can't recover from S3)

set -euo pipefail

# livesys-scripts (configured further down in build.sh) creates the
# `liveuser` account; we only need to wire up SDDM autologin to land
# in the Plasma session immediately, disable screen-lock + power-suspend
# (an installer mid-run can't recover from S3), and mask suspend
# targets so KDE's own power-management prefs can't override.

mkdir -p /etc/sddm.conf.d
tee /etc/sddm.conf.d/live-autologin.conf <<'SDDMEOF'
[General]
DisplayServer=wayland
CompositorCommand=kwin_wayland --no-lockscreen

[Autologin]
User=liveuser
Session=plasma
Relogin=false
SDDMEOF

mkdir -p /etc/xdg
tee /etc/xdg/kscreenlockerrc <<'LOCKEOF'
[Daemon]
Autolock=false
LockOnResume=false
LOCKEOF

tee /etc/xdg/powermanagementprofilesrc <<'POWEREOF'
[AC][SuspendSession]
idleTime=0
suspendType=0

[Battery][SuspendSession]
idleTime=0
suspendType=0

[LowBattery][SuspendSession]
idleTime=0
suspendType=0
POWEREOF

# Belt-and-braces: even if the per-user power prefs above are
# ignored, the systemd targets they'd trigger are masked so the
# install session cannot enter S3.
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target || true

# Auto-launch the TunaOS installer frontend in the live session.
# The app is baked into the live squash by customize-live.sh (tacklebox live_customize).
mkdir -p /etc/xdg/autostart
tee /etc/xdg/autostart/org.tunaos.installer-live.desktop <<'DESKEOF'
[Desktop Entry]
Type=Application
Name=Install TunaOS
Exec=flatpak run org.tunaos.InstallerKde
Icon=org.tunaos.InstallerKde
OnlyShowIn=KDE;
X-KDE-autostart-phase=2
DESKEOF
