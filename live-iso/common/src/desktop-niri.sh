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
	tee /etc/greetd/config.toml <<'GREETDEOF'
[terminal]
vt = 1

[initial_session]
user = "liveuser"
command = "niri-session"

[default_session]
user = "liveuser"
command = "niri-session"
GREETDEOF
else
	tee /etc/greetd/config.toml <<'GREETDEOF'
[terminal]
vt = 1

[initial_session]
user = "liveuser"
command = "niri-session"

[default_session]
user = "liveuser"
command = "niri-session"
GREETDEOF
fi

# Ensure greetd actually runs on boot: enable the service and make
# graphical.target the default. Without this the live env boots to
# multi-user.target and lands on a text console (tunaOS#678).
systemctl enable greetd.service 2>/dev/null || true
ln -sf /usr/lib/systemd/system/greetd.service /etc/systemd/system/display-manager.service 2>/dev/null || true
systemctl set-default graphical.target 2>/dev/null ||
	ln -sf /usr/lib/systemd/system/graphical.target /etc/systemd/system/default.target 2>/dev/null || true

# Disable screen lock for the live session
mkdir -p /etc/xdg
tee /etc/xdg/niri-session.override <<'NIRIEOF'
[idle]
inhibit-when-fullscreen = false

[bind]
mod = Super
NIRIEOF

# Mask sleep targets so the installer session cannot enter S3
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target || true

# Installer frontend: launch it at session start.
#
# This used to be a TODO ("add spawn-at-startup to the niri config when the
# live config.kdl is introduced") and the effect was that org.tunaos.
# InstallerNiri got baked into the live squash and then never started — the
# user had to find it in the DMS launcher on an installer ISO. gnome had the
# same gap; see desktop-gnome.sh.
#
# A systemd user unit rather than spawn-at-startup, because this script writes
# /etc/xdg/niri-session.override and not a config.kdl: dropping a partial
# /etc/niri/config.kdl would REPLACE niri's default config, taking the
# keybinds and output setup with it. niri-session runs a systemd user session
# and reaches graphical-session.target, so a unit bound to it starts the
# installer without touching niri's own configuration at all.
mkdir -p /usr/lib/systemd/user
tee /usr/lib/systemd/user/tunaos-installer-live.service <<'UNITEOF'
[Unit]
Description=TunaOS installer (live session)
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/flatpak run org.tunaos.InstallerNiri
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
UNITEOF

# Enable for every user rather than relying on `systemctl --user enable` at
# first login, which never runs on a live ISO that logs straight in.
mkdir -p /usr/lib/systemd/user/graphical-session.target.wants
ln -sf ../tunaos-installer-live.service \
	/usr/lib/systemd/user/graphical-session.target.wants/tunaos-installer-live.service
