#!/usr/bin/env bash
# Pantheon runs gnome-setup too (GTK 4 and libadwaita run under Gala): same build.
set -euo pipefail
exec "$(dirname "${BASH_SOURCE[0]}")/../gnome/build.sh" "$@"
