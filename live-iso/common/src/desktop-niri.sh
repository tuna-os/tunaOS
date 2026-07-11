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

[default_session]
type = "login_manager"
user = "liveuser"
command = "/usr/bin/dms-greeter"

[initial_session]
user = "liveuser"
command = "niri-session"
GREETDEOF
else
	tee /etc/greetd/config.toml <<'GREETDEOF'
[terminal]
vt = 1

[default_session]
type = "login_manager"
user = "liveuser"
command = "niri-session"

[initial_session]
user = "liveuser"
command = "niri-session"
GREETDEOF
fi

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
# flatpak-preinstalled (build_scripts/installer-frontend.sh) and launched from
# the shell / DMS launcher. Add spawn-at-startup to the niri config when the
# live config.kdl is introduced.
