#!/usr/bin/env bash
# Build gate (tunaOS#5005): /var/run is a symlink to ../run, never a directory.
#
# albacore:gnome shipped /var/run as a real directory holding spice-vdagentd.
# systemd-tmpfiles (var.conf: `L /var/run - - - - ../run`) does not replace a
# directory, so the link never appeared. The D-Bus default system bus address
# is /var/run/dbus/system_bus_socket; clients that use it (zbus) failed with
# "No such file or directory".
#
# A package scriptlet can recreate the directory in any layer, so this runs at
# the end of the base stage (99-cleanup.sh) and of the desktop stage
# (desktop/tuna-flatpak-remote.sh). Anything in the directory is runtime state
# that /run recreates at boot, so it is moved into /run, not kept.
#
# TUNAOS_ROOT points the script at another tree (tests only).
set -euo pipefail

root="${TUNAOS_ROOT:-}"
var_run="${root}/var/run"

if [[ -d "${var_run}" && ! -L "${var_run}" ]]; then
	echo "fix-var-run: ${var_run} is a directory; replacing it with a link to ../run"
	mkdir -p "${root}/run"
	if [[ -n "$(ls -A "${var_run}")" ]]; then
		cp -a "${var_run}/." "${root}/run/"
	fi
	rm -rf "${var_run}"
fi

if [[ ! -e "${var_run}" && ! -L "${var_run}" ]]; then
	mkdir -p "${root}/var"
	ln -s ../run "${var_run}"
fi

if [[ "$(readlink "${var_run}")" != "../run" ]]; then
	echo "ERROR: fix-var-run: ${var_run} is not a link to ../run (tunaOS#5005)" >&2
	exit 1
fi
