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

# openSUSE names the session plasmawayland.desktop; everyone else plasma.
_kde_session="plasma"
if [[ -f /usr/share/wayland-sessions/plasmawayland.desktop && ! -f /usr/share/wayland-sessions/plasma.desktop ]]; then
	_kde_session="plasmawayland"
fi
# KDE 6.5+ renames the SDDM binary/unit to plasmalogin, and with it the
# config directory (/etc/plasmalogin.conf.d). Both names are in the wild —
# yellowfin:kde shipped sddm in July 2026 and plasmalogin days later — so
# write the drop-in to every candidate directory rather than detecting.
# A drop-in in a directory no DM reads is inert, so this is free.
# Getting this wrong is silent: the greeter simply prompts for a password
# and the live session (and installer) never starts.
for _kde_confd in /etc/sddm.conf.d /etc/plasmalogin.conf.d; do
	mkdir -p "${_kde_confd}"
	# CompositorCommand lives in [Wayland]. Under [General] (where it used to
	# be) SDDM drops it as an unknown key without a word, and the greeter
	# falls back to its built-in "weston --shell=kiosk". The value is the one
	# Fedora's own sddm-wayland-plasma config ships.
	tee "${_kde_confd}/live-autologin.conf" <<SDDMEOF
[General]
DisplayServer=wayland

[Wayland]
CompositorCommand=kwin_wayland --drm --no-lockscreen --no-global-shortcuts --locale1

[Autologin]
User=liveuser
Session=${_kde_session}
Relogin=false
SDDMEOF
done

# SDDM (and its PlasmaLogin fork) only reads its config when the newest
# mtime among /etc/sddm.conf, the conf.d directories and their files is a
# valid time; otherwise ConfigBase::load() returns before reading anything.
# Qt reports an mtime of 0 as an *invalid* QDateTime, and the browser ISO
# builder grafts this live overlay with every mtime set to 0. On a base that
# ships no SDDM config of its own (grouper/Ubuntu: no /etc/sddm.conf, no
# /usr/lib/sddm/sddm.conf.d) the drop-ins above are then the only files, all
# at 0, and SDDM silently runs on built-in defaults: DisplayServer=x11, no
# autologin. MEASURED on the grouper:kde pilot ISO (tunaOS#4459):
#
#   sddm: Loaded empty theme configuration
#   sddm: Running: /usr/bin/X -nolisten tcp ... vt2
#   sddm: Failed to start display server process.
#
# (grouper ships no X server), so the screen stayed black and no session, and
# no installer, ever started. Fedora bases hid this because their own
# /usr/lib/sddm/sddm.conf.d files carry real mtimes. Stamp the directories
# with the boot time before the display manager reads them. ($$ is systemd's
# escape for a literal $ in ExecStart; a bare $d would be expanded to empty.)
tee /etc/systemd/system/tunaos-live-dm-config.service <<'DMCFGEOF'
[Unit]
Description=Give the live display-manager config a readable mtime
DefaultDependencies=no
After=local-fs.target
Before=display-manager.service sddm.service plasmalogin.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'for d in /etc/sddm.conf.d /etc/plasmalogin.conf.d; do [ -d "$$d" ] && touch -c "$$d" "$$d"/*; done; exit 0'

[Install]
WantedBy=display-manager.service
DMCFGEOF
for _dm_unit in display-manager.service sddm.service plasmalogin.service; do
	mkdir -p "/etc/systemd/system/${_dm_unit}.wants"
	ln -sf /etc/systemd/system/tunaos-live-dm-config.service \
		"/etc/systemd/system/${_dm_unit}.wants/tunaos-live-dm-config.service"
done

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
# NOTE: deliberately no OnlyShowIn=. systemd-xdg-autostart-generator turns
# each entry into a unit whose ExecCondition is
# `systemd-xdg-autostart-condition "<desktop>"`, evaluated against
# $XDG_CURRENT_DESKTOP in the *user manager's* environment. cosmic-session
# does not export it, so on a live cosmic ISO every OnlyShowIn entry is
# generated and then skipped:
#
#   app-org.tunaos.installer\x2dlive@autostart.service: Skipped due to
#   'exec-condition'  (verified on hardware, 2026-07-26)
#
# gnome-keyring and CosmicInitialSetup were skipped the same way, which is
# the tell: it is not our entry that is wrong, it is the filter. A live ISO
# runs exactly one desktop, so OnlyShowIn buys nothing and costs the whole
# feature.
mkdir -p /etc/xdg/autostart
tee /etc/xdg/autostart/org.tunaos.installer-live.desktop <<DESKEOF
[Desktop Entry]
Type=Application
Name=Install ${TUNAOS_PROJECT_NAME:?set by customize-live.sh from identity-config.env}
Exec=flatpak run org.tunaos.InstallerKde
Icon=org.tunaos.InstallerKde
X-KDE-autostart-phase=2
DESKEOF
