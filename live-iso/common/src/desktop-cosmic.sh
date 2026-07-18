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

# greetd autologin: initial_session logs liveuser straight into COSMIC on
# boot; default_session relaunches it if the session exits (live kiosk).
# NOTE: no 'type' key — that is not valid greetd TOML and makes greetd
# reject the whole config, falling back to the image's greeter.
[initial_session]
user = "liveuser"
command = "cosmic-session"

[default_session]
user = "liveuser"
command = "cosmic-session"
GREETDEOF

# Ensure greetd actually runs on boot: enable the service and make
# graphical.target the default. Without this the live env boots to
# multi-user.target and lands on a text console (tunaOS#678).
systemctl enable greetd.service 2>/dev/null || true
ln -sf /usr/lib/systemd/system/greetd.service /etc/systemd/system/display-manager.service 2>/dev/null || true
systemctl set-default graphical.target 2>/dev/null || \
  ln -sf /usr/lib/systemd/system/graphical.target /etc/systemd/system/default.target 2>/dev/null || true

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

# Auto-launch the TunaOS installer frontend in the live session.
# The app is baked into the live squash by customize-live.sh (tacklebox live_customize).
mkdir -p /etc/xdg/autostart
tee /etc/xdg/autostart/org.tunaos.installer-live.desktop <<'DESKEOF'
[Desktop Entry]
Type=Application
Name=Install TunaOS
Exec=flatpak run org.tunaos.InstallerCosmic
Icon=org.tunaos.InstallerCosmic
OnlyShowIn=COSMIC;
DESKEOF
