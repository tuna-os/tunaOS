#!/usr/bin/env bash
# Tuna Desktop live session: gnome-setup, autostarted (tunaOS#4905).
# Contract: frontends/README.md. Run by install-frontend.sh.
#
# Tuna Desktop runs gnome-shell and logs in through GDM ([desktops.tuna]
# display_manager = "gdm" in tunaos.toml), so it takes the GNOME frontend
# unchanged: gnome-setup, the extension that closes the startup overview, and
# the GDM autologin of medium-live-setup. Only the name differs, because the
# dispatcher checks payload.d/tuna.list and stamp.d/tuna.
set -euo pipefail
MEDIUM_FRONTEND_NAME=tuna exec "${MEDIUM_FRONTENDS:?run through install-frontend.sh}/gnome/install.sh" "$@"
