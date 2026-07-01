#!/usr/bin/env bash
# Live ISO desktop adapter: COSMIC
# Sourced by live-iso/common/src/build.sh for cosmic* desktop flavors.
#
# Configures:
#   - greetd + cosmic-greeter autologin
#   - Disable screen lock + power suspend
#   - Mask suspend targets

set -euo pipefail

# greetd autologin: drop straight into a COSMIC session without prompting.
mkdir -p /etc/greetd
tee /etc/greetd/config.toml <<'GREETDEOF'
[terminal]
vt = 1

[default_session]
type = "login_manager"
user = "liveuser"
command = "cosmic-session"

[initial_session]
user = "liveuser"
command = "cosmic-session"
GREETDEOF

# Disable screen lock for the live session
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
