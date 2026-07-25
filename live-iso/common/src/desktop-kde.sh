#!/usr/bin/env bash
# Live ISO desktop adapter: KDE Plasma
# Sourced by live-iso/common/src/build.sh for kde* desktop flavors.
#
# Configures:
#   - SDDM/PlasmaLogin autologin to Plasma session (Wayland, no lockscreen)
#   - Disable screen lock + power suspend
#   - Mask suspend targets (installer can't recover from S3)

set -euo pipefail

# livesys-scripts (configured further down in build.sh) creates the
# `liveuser` account; we only need to wire up DM autologin to land
# in the Plasma session immediately, disable screen-lock + power-suspend
# (an installer mid-run can't recover from S3), and mask suspend
# targets so KDE's own power-management prefs can't override.

# openSUSE names the session plasmawayland.desktop; everyone else plasma.
_kde_session="plasma"
if [[ -f /usr/share/wayland-sessions/plasmawayland.desktop && ! -f /usr/share/wayland-sessions/plasma.desktop ]]; then
	_kde_session="plasmawayland"
fi

# Plasma 6.6 renamed SDDM to PlasmaLogin: on EL10 the `plasma-login-manager`
# package ships plasmalogin.service and reads /etc/plasmalogin.conf.d, and it
# arrives as a plasma-group dependency *before* our explicit `sddm` install.
# It does not Obsolete sddm, so both units exist and plasmalogin wins the
# display-manager.service alias. Dropping autologin only into /etc/sddm.conf.d
# therefore silently did nothing and the live ISO stopped at a password prompt
# (installer-smoke run 29914643652: 4 minutes of greeter, no installer).
#
# The two read the same [Autologin] schema, so write whichever conf.d dirs
# this image actually has. PlasmaLogin is Wayland-only and has no equivalent
# of SDDM's [General] DisplayServer/CompositorCommand, so those stay
# sddm-only rather than being emitted as keys it would ignore.
_wrote_autologin=false

if [[ -d /usr/lib/plasmalogin || -e /usr/lib/systemd/system/plasmalogin.service ]]; then
	mkdir -p /etc/plasmalogin.conf.d
	tee /etc/plasmalogin.conf.d/live-autologin.conf <<PLEOF
[Autologin]
User=liveuser
Session=${_kde_session}
Relogin=false
PLEOF
	_wrote_autologin=true
fi

if [[ -d /usr/lib/sddm || -e /usr/lib/systemd/system/sddm.service ]]; then
	mkdir -p /etc/sddm.conf.d
	tee /etc/sddm.conf.d/live-autologin.conf <<SDDMEOF
[General]
DisplayServer=wayland
CompositorCommand=kwin_wayland --no-lockscreen

[Autologin]
User=liveuser
Session=${_kde_session}
Relogin=false
SDDMEOF
	_wrote_autologin=true
fi

# A KDE live ISO whose greeter never auto-logs in cannot reach the installer,
# which is precisely the failure this guards against — fail the build loudly
# rather than shipping an ISO that stops at a password prompt.
if [[ "${_wrote_autologin}" != true ]]; then
	echo "desktop-kde: no SDDM or PlasmaLogin install found — cannot configure live autologin" >&2
	exit 1
fi

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

# KDE's Welcome Center (plasma-welcome) launches itself on first login and
# lands ON TOP of the installer — run 30166081962 photographed its generic
# onboarding tour, not the installer, and the installer window was never
# raised. Its default content is also wrong for a live session: it teaches
# you to customize a system that disappears on reboot.
#
# plasma-welcome supports this case explicitly (see its README, shipped at
# /usr/share/doc/plasma-welcome/README.md): LiveEnvironment=true swaps the
# settings pages for a reduced wizard with a live installer page, and
# LiveInstaller names a desktop file in the applications path to offer as the
# launch shortcut.
#
# Written to /etc/xdg rather than ~liveuser/.config so it applies however the
# live user is created — livesys-scripts, tacklebox's baseline, or neither.
if [[ -f /usr/share/applications/org.kde.plasma-welcome.desktop ]]; then
    mkdir -p /etc/xdg
    tee /etc/xdg/plasma-welcomerc <<'WELCOMEEOF'
[General]
LiveEnvironment=true
LiveInstaller=org.tunaos.InstallerKde
WELCOMEEOF
fi

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
