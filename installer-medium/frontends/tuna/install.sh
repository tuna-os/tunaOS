#!/usr/bin/env bash
# Tuna Desktop live session: gnome-setup, autostarted (tunaOS#4905).
# Contract: frontends/README.md. Run by install-frontend.sh.
#
# Tuna Desktop logs in through GDM ([desktops.tuna] display_manager = "gdm"
# in tunaos.toml) and runs GTK 4 apps, so it takes the GNOME frontend:
# gnome-setup and the GDM autologin of medium-live-setup. Its session is
# tuna-session, not gnome-shell, and runs no XDG autostart entries, so
# tuna/session.sh adds a user unit that starts the installer. The name
# differs because the dispatcher checks payload.d/tuna.list and stamp.d/tuna.
set -euo pipefail
MEDIUM_FRONTEND_NAME=tuna exec "${MEDIUM_FRONTENDS:?run through install-frontend.sh}/gnome/install.sh" "$@"
