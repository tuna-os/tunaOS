#!/usr/bin/env bash
# Live ISO desktop adapter: Niri
# Sourced by live-iso/common/src/build.sh for niri* desktop flavors.
#
# Configures:
#   - greetd + dms-greeter autologin
#   - Or fall back to basic greetd + niri-session
#   - Disable screen lock + power suspend
#   - Mask suspend targets

set -euo pipefail

# greetd autologin: drop straight into a Niri session.
# Prefer dms-greeter (from DankMaterialShell) if available, otherwise
# use a minimal niri-session directly.
mkdir -p /etc/greetd

if command -v dms-greeter &>/dev/null; then
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

[initial_session]
user = "liveuser"
command = "systemd-cat -t tunaos-live-session niri-session"

[default_session]
user = "liveuser"
command = "systemd-cat -t tunaos-live-session niri-session"
GREETDEOF
else
	tee /etc/greetd/config.toml <<'GREETDEOF'
[terminal]
vt = 1

[initial_session]
user = "liveuser"
command = "systemd-cat -t tunaos-live-session niri-session"

[default_session]
user = "liveuser"
command = "systemd-cat -t tunaos-live-session niri-session"
GREETDEOF
fi

# Ensure greetd actually runs on boot: enable the service and make
# graphical.target the default. Without this the live env boots to
# multi-user.target and lands on a text console (tunaOS#678).
systemctl enable greetd.service 2>/dev/null || true
ln -sf /usr/lib/systemd/system/greetd.service /etc/systemd/system/display-manager.service 2>/dev/null || true
systemctl set-default graphical.target 2>/dev/null ||
	ln -sf /usr/lib/systemd/system/graphical.target /etc/systemd/system/default.target 2>/dev/null || true

# The block that used to be here wrote /etc/xdg/niri-session.override with
# INI-style [idle] and [bind] sections. niri has no such file and no such
# format — its configuration is KDL, at ~/.config/niri/config.kdl,
# /etc/niri/config.kdl or (on TunaOS) /usr/share/niri/config.kdl. Nothing in
# the image or in niri read that path, so it configured nothing; it only made
# the live session look configured. Removed rather than ported, because there
# is nothing to port to: the config.kdl this image ships spawns no swayidle or
# swaylock, so there is no screen lock to disable in the first place. Sleep is
# handled for real by the systemctl mask below.

# Mask sleep targets so the installer session cannot enter S3
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target || true

# Installer frontend: launch it at session start.
#
# This used to be a TODO — "add spawn-at-startup to the niri config when the
# live config.kdl is introduced" — and the effect was that
# org.tunaos.InstallerNiri got baked into the live squash and then never
# started, on an ISO whose only purpose is to run it. gnome had the same gap;
# see desktop-gnome.sh.
#
# The TODO is stale: the config.kdl already exists. TunaOS ships one at
# /usr/share/niri/config.kdl (system_files/) as the compositor default, and it
# already drives the whole session this way — swaybg, waybar, nm-applet,
# swaync and cliphist are all spawn-at-startup lines in it. So this appends one
# more to the file that is already there, rather than creating
# /etc/niri/config.kdl, which would REPLACE that default and take the keybinds,
# output setup and window rules with it.
#
# Appending to the shipped default is also why this is preferred over a systemd
# user unit: spawn-at-startup is niri's own idiom and is demonstrably working
# in this exact image, whereas a user unit would rest on an assumption about
# how far niri-session takes graphical-session.target.
# niri reads exactly ONE config -- the first of these that exists:
#
#   $XDG_CONFIG_HOME/niri/config.kdl   (liveuser's ~/.config/niri/config.kdl)
#   /etc/niri/config.kdl
#   /usr/share/niri/config.kdl
#
# This appended only to the LAST one, and run 32450214451 proved that never
# takes effect. niri came up fine (pid 2083, socket wayland-1) and said so
# itself:
#
#   niri_config: loaded config from "/var/home/liveuser/.config/niri/config.kdl"
#
# The niri package ships a skel copy, useradd --create-home installs it into
# liveuser's home at customize-live.sh:81 -- fifteen lines before this script
# is sourced -- and from then on the system default is dead weight. The
# flatpak was installed and correct; `flatpak ps` was simply empty, because
# nothing ever launched it. Exactly the read-path failure this repo keeps
# hitting: the fix landed somewhere the target never looks.
#
# So append to every candidate that exists rather than guessing which wins.
# niri reads one, so this cannot double-spawn, and it does not have to model
# a precedence order that may change.
_niri_home="$(getent passwd liveuser | cut -d: -f6)"
NIRI_CONFIGS=(
	"${_niri_home:-/var/home/liveuser}/.config/niri/config.kdl"
	/etc/niri/config.kdl
	/usr/share/niri/config.kdl
)
_niri_appended=0
for _niri_cfg in "${NIRI_CONFIGS[@]}"; do
	[[ -f "${_niri_cfg}" ]] || continue
	tee -a "${_niri_cfg}" <<'NIRIEOF'

// ── live ISO only ────────────────────────────────────────────────────────────
// Appended by live-iso/common/src/desktop-niri.sh. Installed systems never see
// this line: it is written into the live squash, not into the deployed image.
spawn-at-startup "flatpak" "run" "org.tunaos.InstallerNiri"
NIRIEOF
	echo "desktop-niri: installer autostart appended to ${_niri_cfg}"
	_niri_appended=$((_niri_appended + 1))
done

if [[ "${_niri_appended}" -eq 0 ]]; then
	# Fatal on purpose. A live niri ISO with no installer launcher is the exact
	# defect this block exists to close, and it is invisible from outside — the
	# ISO builds, the VM boots, the desktop comes up, and nothing runs.
	echo "desktop-niri: no niri config.kdl found in any of ${NIRI_CONFIGS[*]}; cannot arrange installer autostart" >&2
	exit 1
fi
