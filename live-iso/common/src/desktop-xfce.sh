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
# xfwl4 is listed first: it is what the EL10 manifest installs, and run
# 30191933429 shows `startxfce4 --wayland xfwl4` really does launch it —
# xfwl4 came up on renderD128 and created wayland-1 before panicking on
# "Failed to find theme named Default" (missing xfwm4 theme data,
# tunaos-packages#123). An earlier revision of this file excluded xfwl4 on
# the theory that startxfce4 appends no startup command to a named
# compositor; that reasoning was not borne out, and excluding it was
# strictly worse — the X11 branch is a dead end on a base that ships no
# /usr/share/xsessions at all. Whether xfce4-session follows xfwl4 up is
# still unproven: xfwl4 dies before we find out.
_xfce_compositor=""
for _c in xfwl4 labwc wayfire; do
	command -v "${_c}" &>/dev/null && {
		_xfce_compositor="${_c}"
		break
	}
done

if [[ -n "${_xfce_compositor}" ]] && command -v greetd &>/dev/null; then
	# ── Wayland (xfwl4) — greetd autologin, no X11 ───────────────────────
	# greetd `command` is run by the user's shell, so it must be the actual
	# exec, not a session-file name. dbus-run-session gives the session a
	# message bus (portals, xfconf) the way a DM login would.
	echo "desktop-xfce: wayland session via compositor=${_xfce_compositor}"
	mkdir -p /etc/greetd
	# WHY systemd-cat WRAPS EVERY SESSION COMMAND HERE
	#
	# greetd runs `command` and captures nothing. When the session exits
	# immediately, the journal records the bookkeeping and not one line from the
	# process that died:
	#
	#   greetd[1240]: pam_unix(greetd:session): session opened for user liveuser
	#   greetd[1981]: pam_unix(greetd-greeter:session): session closed for user liveuser
	#   greetd[1231]: error: check_children: greeter exited without creating a session
	#
	# repeated five times to start-limit-hit (smoke run 32681262659, xfce). That
	# message names greetd's bookkeeping, never the compositor's reason, and it
	# is the entire evidence base on which this failure has been attributed to a
	# missing DRM render node. The same run disproves that attribution: the guest
	# has /dev/dri/renderD128, and the kernel reports
	#
	#   [drm] pci: virtio-vga detected at 0000:00:02.0
	#   [drm] features: -virgl +edid -resource_blob -host_visible
	#
	# so the node is there and 3D is not, which is a different claim needing
	# different evidence.
	#
	# systemd-cat execs the program with stdout and stderr on the journal and
	# passes the exit status through, so `journalctl -t tunaos-live-session` now
	# holds whatever the compositor said on its way out. Nothing about what runs
	# changes. This is the same remedy that ended four wrong guesses at
	# gnome-desktop:languages in the package factory -- make the failing thing
	# print its own log, then read it.
	tee /etc/greetd/config.toml <<GREETDEOF
[terminal]
vt = 1

[default_session]
user = "liveuser"
command = "systemd-cat -t tunaos-live-session dbus-run-session startxfce4 --wayland ${_xfce_compositor}"

[initial_session]
user = "liveuser"
command = "systemd-cat -t tunaos-live-session dbus-run-session startxfce4 --wayland ${_xfce_compositor}"
GREETDEOF
	# Enable greetd + boot to graphical.target (server-oriented EL10 bases
	# default to multi-user.target, which would land on a console — same
	# root cause as tunaOS#678 for niri/cosmic).
	systemctl enable greetd.service 2>/dev/null || true
	ln -sf /usr/lib/systemd/system/greetd.service /etc/systemd/system/display-manager.service 2>/dev/null || true
	systemctl set-default graphical.target 2>/dev/null ||
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
tee /etc/xdg/autostart/org.tunaos.installer-live.desktop <<'DESKEOF'
[Desktop Entry]
Type=Application
Name=Install TunaOS
Exec=flatpak run org.tunaos.InstallerXfce
Icon=org.tunaos.InstallerXfce
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
