#!/usr/bin/env bash
# Live ISO desktop adapter: COSMIC
# Sourced by live-iso/common/src/build.sh for cosmic* desktop flavors.
#
# Configures:
#   - greetd + cosmic-session autologin (masking the packaged
#     cosmic-greeter.service, which otherwise races it for vt1)
#   - Disable screen lock + power suspend
#   - Mask suspend targets

set -euo pipefail

# greetd autologin: drop straight into a COSMIC session without prompting.
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
tee /etc/greetd/config.toml <<'GREETDEOF'
[terminal]
vt = 1

# greetd's source_profile default is what stops the live session dead.
#
# With it on (the default), greetd does not exec the command directly — it
# wraps it:
#
#   /bin/sh -c '[ -f /etc/profile ] && . /etc/profile; \
#               [ -f $HOME/.profile ] && . $HOME/.profile; exec <command>'
#
# MEASURED on a marlin:cosmic dev ISO, inside the live guest over SSH:
#
#   859 S+  do_wait     /bin/sh -c ... . /etc/profile; ... exec cosmic-session
#   882 Sl+ wait_woken  umotd
#
# `umotd` (from /etc/profile.d/umotd.sh, shipped by the ublue common payload)
# blocks in a non-interactive session, the shell sits in do_wait forever, and
# `exec` is never reached. greetd itself is healthy, autologin works
# ("pam_unix(greetd:session): session opened for user liveuser"), no unit
# fails, graphical.target is active — and there is still no compositor and no
# installer on screen. It looks exactly like a broken desktop.
#
# The live session does not need login-profile side effects; its environment
# comes from the user systemd session. Turning source_profile off removes the
# whole class of "something in profile.d blocks the greeter's exec", not just
# this one instance.
[general]
source_profile = false

# greetd autologin: initial_session logs liveuser straight into COSMIC on
# boot; default_session relaunches it if the session exits (live kiosk).
# NOTE: no 'type' key — that is not valid greetd TOML and makes greetd
# reject the whole config, falling back to the image's greeter.
[initial_session]
user = "liveuser"
command = "systemd-cat -t tunaos-live-session cosmic-session"

[default_session]
user = "liveuser"
command = "systemd-cat -t tunaos-live-session cosmic-session"
GREETDEOF

# Ensure greetd actually runs on boot: enable the service and make
# graphical.target the default. Without this the live env boots to
# multi-user.target and lands on a text console (tunaOS#678).
systemctl enable greetd.service 2>/dev/null || true
ln -sf /usr/lib/systemd/system/greetd.service /etc/systemd/system/display-manager.service 2>/dev/null || true
systemctl set-default graphical.target 2>/dev/null ||
	ln -sf /usr/lib/systemd/system/graphical.target /etc/systemd/system/default.target 2>/dev/null || true

# Mask the packaged cosmic-greeter.service (tunaOS#678). On EL10 (yellowfin)
# it ships with `[Install] WantedBy=graphical.target` and NO
# `Alias=display-manager.service` — unlike Debian/Ubuntu's cosmic-greeter
# deb, which claims the alias and would at least get overridden by the
# `ln -sf` above. Without an alias to override, re-pointing
# display-manager.service does nothing to it: it is independently pulled in
# by graphical.target and starts anyway, alongside our greetd.service,
# racing it for vt1.
#
# CONFIRMED via installer-smoke run 31229915708 (yellowfin:cosmic): both
# units start in the same second —
#
#   Started cosmic-greeter.service - COSMIC Greeter.
#   Started greetd.service - Greeter daemon.
#   greetd[1235]: pam_unix(greetd-greeter:session): session opened for user
#     cosmic-greeter(uid=974) ...
#   greetd[1207]: error: check_children: greeter exited without creating a
#     session
#   cosmic-greeter.service: Scheduled restart job, restart counter is at 1.
#   ...
#   greetd[2680]: pam_unix(cosmic-greeter:auth): authentication failure;
#     ... user=liveuser
#
# — and cosmic-greeter.service wins vt1: every captured screenshot across
# a full 9-step walkthrough showed its GUI login prompt for liveuser (never
# the desktop), crash-looping and re-showing the password field each
# restart. That is also why prior "compositor is running" checks passed —
# `pgrep -x cosmic-comp` matches cosmic-greeter's OWN compositor, which it
# uses to render its greeter UI, indistinguishably from a real session's.
#
# `mask` (not `disable`): disable only removes the WantedBy symlink and
# still lets something else start it by name; mask hard-links it to
# /dev/null so nothing — not graphical.target, not a dependency, not a
# manual `systemctl start` from another script run later in this same
# pipeline — can bring it up again.
systemctl mask cosmic-greeter.service 2>/dev/null ||
	ln -sf /dev/null /etc/systemd/system/cosmic-greeter.service 2>/dev/null || true

# Disable idle screen-off / lock / suspend for the live session.
#
# cosmic-idle is what actually locks the session: its binary contains both
# `loginctl lock-session` and `systemctl suspend`, and it reads its timers from
# the cosmic-config store `com.system76.CosmicIdle` (keys: screen_off_time,
# suspend_on_ac_time, suspend_on_battery_time) — NOT from the
# cosmic-settings-daemon override written below, which it never opens. So the
# override alone left a live ISO able to lock itself, and liveuser is
# passwordless, which is a poor place to end up.
#
# cosmic-config is one file per key holding a RON value; `None` disables an
# Option-typed timer (see /usr/share/cosmic/com.system76.CosmicAppList/v1/
# filter_top_levels, which is literally "None"). Written to /usr/share/cosmic
# because that is where this image's defaults demonstrably live, and to
# /etc/cosmic as the sysadmin-override location, so this does not depend on
# which of the two libcosmic happens to consult first.
for _cosmic_root in /usr/share/cosmic /etc/cosmic; do
	mkdir -p "${_cosmic_root}/com.system76.CosmicIdle/v1"
	for _k in screen_off_time suspend_on_ac_time suspend_on_battery_time; do
		echo "None" >"${_cosmic_root}/com.system76.CosmicIdle/v1/${_k}"
	done
done

# Kept as well: this is the right home for the power/time settings the
# settings daemon itself owns, even though it is not what gates the lock.
mkdir -p /etc/xdg
tee /etc/xdg/cosmic-settings-daemon.override <<'COSMICEOF'
[time]
manual_datetime = false
automatic_timezone = true

[power]
auto_suspend = false
auto_suspend_on_battery = false
screen_blank = 0
screen_lock = false
COSMICEOF

# Mask sleep targets so the installer session cannot enter S3
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
Exec=flatpak run org.tunaos.InstallerCosmic
Icon=org.tunaos.InstallerCosmic
DESKEOF

# openSUSE Tumbleweed's greetd ships NO PAM services (sailfin-cosmic, iso-builder run
# 43541246573, serial dump: `ls /etc/pam.d/greetd*` -> No such file, greetd.service
# start-limit-hit after "greeter exited without creating a session" x5), so PAM falls back
# to `other` (deny) and the live session never starts: black screen (tunaOS#4538). Give the
# live session both services when the distro provides neither. Autologin of the passwordless
# liveuser needs no authentication, so auth is permit; sessions go through the distro stack.
for _svc in greetd greetd-greeter; do
	if [[ ! -e /etc/pam.d/${_svc} && ! -e /usr/lib/pam.d/${_svc} ]]; then
		mkdir -p /etc/pam.d
		cat >/etc/pam.d/${_svc} <<'PAMEOF'
#%PAM-1.0
auth     required  pam_permit.so
account  required  pam_permit.so
password required  pam_deny.so
session  required  pam_unix.so
session  optional  pam_systemd.so
PAMEOF
	fi
done

# WHY THE SESSION REPORTS ITSELF ON THE SERIAL CONSOLE
#
# greetd captures nothing and the strict harness executes nothing in the guest, so a
# live session that dies leaves only black frames: sailfin-cosmic (iso-builder runs
# 43356224963, 43568760716) stayed black with the contract green and no line from the
# compositor in the serial log. systemd-cat above puts the compositor's own output in
# the journal under `tunaos-live-session`; this copies it, with greetd's unit state and
# the processes, to the serial console where the harness already keeps a log. Silent
# unless the kernel console is a serial port; never fails the boot.
install -Dm0755 /dev/stdin /usr/libexec/tunaos/cosmic-live-session-report <<'REPORTEOF'
#!/usr/bin/env bash
# Not set -e: every section is best effort.
grep -q 'console=ttyS' /proc/cmdline 2>/dev/null || exit 0
[[ -w /dev/ttyS0 ]] || exit 0
{
	echo "TUNAOS_COSMIC_SESSION_REPORT uptime=$(cut -d. -f1 /proc/uptime)"
	echo "-- greetd.service"
	systemctl status greetd.service --no-pager -l 2>&1 | head -n 30
	echo "-- processes"
	pgrep -a 'greetd|cosmic|plymouth' 2>&1 || echo "(none)"
	echo "-- loginctl"
	loginctl list-sessions --no-legend 2>&1
	echo "-- /dev/dri"
	ls -l /dev/dri 2>&1
	echo "-- /etc/pam.d/greetd*"
	ls -l /etc/pam.d/greetd* 2>&1
	echo "-- journal: tunaos-live-session (the compositor's own output)"
	journalctl -b --no-pager -n 80 -t tunaos-live-session 2>&1 | cut -c1-300
	echo "-- /usr/lib/pam.d/greetd* (distro vendor services)"
	for _f in /usr/lib/pam.d/greetd*; do
		echo "## ${_f}"
		cat "${_f}" 2>&1
	done
	echo "-- journal: greetd from the first line (initial_session, then default_session)"
	journalctl -b --no-pager -o short-monotonic -u greetd.service 2>&1 | head -n 70 | cut -c1-300
	echo "-- journal: everything from 7 s to 20 s of boot (the compositor logs as cosmic-session, not under tunaos-live-session)"
	journalctl -b --no-pager -o short-monotonic 2>&1 | awk -F'[][]' '{ t = $2 + 0 } t >= 7 && t <= 20' | head -n 220 | cut -c1-260
	echo "-- pam_systemd module and the user manager"
	ls -l /usr/lib*/security/pam_systemd.so /lib*/security/pam_systemd.so 2>&1
	systemctl status user@1000.service --no-pager -l 2>&1 | head -n 12
	ls -la /run/user/1000 2>&1
	echo "-- the session command as liveuser, run by hand with greetd's bare environment"
	command -v systemd-cat cosmic-session start-cosmic 2>&1
	getent passwd liveuser 2>&1
	ls -ld /home/liveuser 2>&1
	install -d -m 0700 -o liveuser /run/user/1000 2>&1
	timeout 12 runuser -u liveuser -- env -i HOME=/home/liveuser USER=liveuser LOGNAME=liveuser \
		XDG_RUNTIME_DIR=/run/user/1000 XDG_SEAT=seat0 XDG_VTNR=1 XDG_SESSION_TYPE=wayland \
		/bin/sh -c 'exec cosmic-session' 2>&1 | head -n 40 | cut -c1-300
	echo "cosmic-session exit status: ${PIPESTATUS[0]}"
	echo "TUNAOS_COSMIC_SESSION_REPORT_END"
} >/dev/ttyS0 2>&1
exit 0
REPORTEOF
cat >/usr/lib/systemd/system/tunaos-cosmic-live-session-report.service <<'UNITEOF'
[Unit]
Description=Copy the live COSMIC session's output to the serial console

[Service]
Type=oneshot
ExecStart=/usr/libexec/tunaos/cosmic-live-session-report
UNITEOF
cat >/usr/lib/systemd/system/tunaos-cosmic-live-session-report.timer <<'UNITEOF'
[Unit]
Description=Report on the live COSMIC session after boot

[Timer]
OnBootSec=60s
OnBootSec=150s
AccuracySec=1s

[Install]
WantedBy=timers.target
UNITEOF
systemctl enable tunaos-cosmic-live-session-report.timer 2>/dev/null || true
