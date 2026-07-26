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
#
# Gate on a *compositor binary*, not on the packaged session file: several
# bases ship /usr/share/wayland-sessions/xfce-wayland.desktop with no
# compositor behind it, and `startxfce4 --wayland` then dies with
#   "Please either install labwc or specify another compositor as argument"
# onto a black screen — which is exactly how yellowfin:xfce failed.
#
# Only labwc and wayfire qualify. xfwl4 does NOT, even though the EL10
# manifest installs it as the xfce compositor: startxfce4 hands its argument
# no startup command (the labwc default path appends `--session
# xfce4-session`), and `xfwl4 --help` has no equivalent option — so
# `startxfce4 --wayland xfwl4` would come up as a bare compositor with no
# session inside it. labwc has no EL10 build in any configured repo, so on
# those images this correctly falls through to the X11 branch rather than
# claiming a Wayland session we cannot start. See tunaOS#834.
_xfce_compositor=""
for _c in labwc wayfire; do
	command -v "${_c}" &>/dev/null && {
		_xfce_compositor="${_c}"
		break
	}
done
if [[ -z "${_xfce_compositor}" ]] && command -v xfwl4 &>/dev/null; then
	echo "desktop-xfce: xfwl4 present but startxfce4 cannot drive it (no startup-command option) and labwc/wayfire are absent; falling back to X11" >&2
fi

if [[ -n "${_xfce_compositor}" ]] && command -v greetd &>/dev/null; then
	# ── Wayland (xfwl4) — greetd autologin, no X11 ───────────────────────
	# greetd `command` is run by the user's shell, so it must be the actual
	# exec, not a session-file name. dbus-run-session gives the session a
	# message bus (portals, xfconf) the way a DM login would.
	echo "desktop-xfce: wayland session via compositor=${_xfce_compositor}"
	mkdir -p /etc/greetd
	tee /etc/greetd/config.toml <<GREETDEOF
[terminal]
vt = 1

[default_session]
user = "liveuser"
command = "dbus-run-session startxfce4 --wayland ${_xfce_compositor}"

[initial_session]
user = "liveuser"
command = "dbus-run-session startxfce4 --wayland ${_xfce_compositor}"
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

	# This branch used to write its configs and stop there, which was only
	# survivable while it ran on bases that already enable a DM and default
	# to graphical.target. Now that a missing compositor can route an EL10
	# image here, do the same enable + set-default the Wayland branch does,
	# or the image boots to a console with a perfectly good autologin config.
	for _dm in lightdm gdm greetd; do
		_unit="/usr/lib/systemd/system/${_dm}.service"
		[[ -f "${_unit}" ]] || continue
		systemctl enable "${_dm}.service" 2>/dev/null || true
		ln -sf "${_unit}" /etc/systemd/system/display-manager.service 2>/dev/null || true
		echo "desktop-xfce: X11 fallback display manager=${_dm}"
		break
	done
	systemctl set-default graphical.target 2>/dev/null ||
		ln -sf /usr/lib/systemd/system/graphical.target /etc/systemd/system/default.target 2>/dev/null || true
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
