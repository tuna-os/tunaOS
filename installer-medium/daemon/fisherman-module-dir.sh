#!/usr/bin/env bash
# Print the directory of fisherman's Go module inside a checkout.
#
# Usage: installer-medium/daemon/fisherman-module-dir.sh CHECKOUT
#
# fisherman's module is at fisherman/ of tuna-os/fisherman (archived
# 2026-11-26). It moved into tuna-os/installer with its history
# (tuna-os/installer#495), where it is at fisherman/fisherman/: the first
# fisherman/ is the project directory. The medium builds from either repo, so
# the layout is read, never assumed. Neither: exit 1.
set -euo pipefail

SRC="${1:?usage: fisherman-module-dir.sh CHECKOUT}"
for dir in "${SRC}/fisherman/fisherman" "${SRC}/fisherman"; do
	if [[ -f "${dir}/go.mod" && -d "${dir}/cmd/fishermand" ]]; then
		echo "${dir}"
		exit 0
	fi
done
echo "fisherman-module-dir: no Go module with cmd/fishermand under ${SRC}/fisherman or ${SRC}/fisherman/fisherman" >&2
exit 1
