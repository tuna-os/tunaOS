#!/usr/bin/env bash
# Live ISO desktop adapter: GNOME
# Sourced by live-iso/common/src/build.sh for gnome* desktop flavors.
#
# Configures:
#   - GNOME dock favorites (FirstSetup, Firefox, Nautilus)
#   - Disable suspend/sleep (installer can't recover from S3)
#   - Compile gschemas

set -euo pipefail

# Set up the GNOME dock for the installer
tee /usr/share/glib-2.0/schemas/zz2-tunaos-installer.gschema.override <<'EOF'
[org.gnome.shell]
welcome-dialog-last-shown-version='4294967295'
favorite-apps = ['org.tunaos.FirstSetup.desktop', 'firefox.desktop', 'org.gnome.Nautilus.desktop']
EOF

# Disable suspend/sleep so the installer doesn't go to sleep mid-install
tee /usr/share/glib-2.0/schemas/zz3-tunaos-installer-power.gschema.override <<'EOF'
[org.gnome.settings-daemon.plugins.power]
sleep-inactive-ac-type='nothing'
sleep-inactive-battery-type='nothing'
sleep-inactive-ac-timeout=0
sleep-inactive-battery-timeout=0

[org.gnome.desktop.session]
idle-delay=uint32 0
EOF

glib-compile-schemas /usr/share/glib-2.0/schemas
