#!/usr/bin/env bash
set -euo pipefail
# Gentoo's user services are not enabled by package installation.  The Tuna
# desktop needs both PipeWire socket entry points and WirePlumber enabled in
# the image-wide user preset so every newly created account gets the audio and
# capture stack without a per-user first-login repair.
if [[ "${PKG_MGR:-}" == emerge ]]; then
	command -v systemctl >/dev/null 2>&1 || {
		echo "Gentoo PipeWire user-service setup requires systemctl" >&2
		exit 1
	}
	systemctl --global enable pipewire.socket pipewire-pulse.socket wireplumber.service
fi
