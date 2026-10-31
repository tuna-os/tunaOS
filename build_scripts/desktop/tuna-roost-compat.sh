#!/usr/bin/env bash
set -euo pipefail

root="${1:-}"
[[ -z "$root" || "$root" == /* ]] || {
	echo "compatibility root must be absolute" >&2
	exit 2
}

# Preserve the one-release Roost command-line compatibility promised for
# upgraded images, even when a Tuna Desktop package omits the legacy links.
for name in compositor session shell-host shell-gtk ibus-bridge; do
	compat="${root}/usr/bin/roost-$name"
	target="${root}/usr/bin/tuna-$name"
	if [[ ! -e "$compat" && ! -L "$compat" && -x "$target" ]]; then
		ln -s "tuna-$name" "$compat"
	fi
done
