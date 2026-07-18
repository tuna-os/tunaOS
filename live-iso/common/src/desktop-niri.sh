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
systemctl set-default graphical.target 2>/dev/null || \
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

# Installer frontend: niri has no XDG autostart; org.tunaos.InstallerNiri is
# baked into the live squash by customize-live.sh and launched from
# the shell / DMS launcher. Add spawn-at-startup to the niri config when the
# live config.kdl is introduced.
