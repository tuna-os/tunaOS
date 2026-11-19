#!/usr/bin/env bash
set -euo pipefail
# Gentoo's user services are not enabled by package installation.  The Tuna
# desktop needs both PipeWire socket entry points and WirePlumber enabled in
# the image-wide user preset so every newly created account gets the audio and
# capture stack without a per-user first-login repair.
#
# Hummingbird's user-preset policy is 90-default-user (dbus only) plus
# 99-default-disable (`disable *`), so the same three units ship disabled
# there (`systemctl --global is-enabled` says disabled for all three). Without
# them hummingbird:tuna's compositor logs "screen cast: PipeWire is not
# running" and every ScreenCast Start goes unanswered.
if [[ "${PKG_MGR:-}" == emerge || "${IS_HUMMINGBIRD:-false}" == true ]]; then
	command -v systemctl >/dev/null 2>&1 || {
		echo "PipeWire user-service setup requires systemctl" >&2
		return 1 2>/dev/null || exit 1
	}
	systemctl --global enable pipewire.socket pipewire-pulse.socket wireplumber.service
fi
