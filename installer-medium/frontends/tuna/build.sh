#!/usr/bin/env bash
# Tuna Desktop shows gnome-setup too (it runs gnome-shell): same build.
set -euo pipefail
exec "$(dirname "${BASH_SOURCE[0]}")/../gnome/build.sh" "$@"
