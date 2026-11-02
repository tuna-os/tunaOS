#!/usr/bin/env bash
# Print the resolved publish destination as "<registry>/<namespace>".
# Precedence and defaults: scripts/lib/publish-destination.sh.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# shellcheck source=lib/build-config.sh
source scripts/lib/build-config.sh
# shellcheck source=lib/publish-destination.sh
source scripts/lib/publish-destination.sh
read -r registry namespace < <(tunaos_publish_destination "$(tunaos_build_config)")
printf '%s/%s\n' "$registry" "$namespace"
