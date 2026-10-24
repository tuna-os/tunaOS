#!/usr/bin/env bash
# Tuna images must log fresh users straight into the Tuna session. GDM falls
# back to its own default (currently the GNOME session, which newer GNOME
# breaks) when the user has no history, so pin the default explicitly.
set -euo pipefail

_TD_ROOT="${TUNAOS_GDM_DEFAULT_ROOT:-}"
_TD_GDM_DIR="${_TD_ROOT}/etc/gdm"
[[ -d "${_TD_ROOT}/etc/gdm3" ]] && _TD_GDM_DIR="${_TD_ROOT}/etc/gdm3"
_TD_GDM_CONFIG="${_TD_GDM_DIR}/custom.conf"

if [[ -f "$_TD_GDM_CONFIG" ]] && grep -q '^\[daemon\]' "$_TD_GDM_CONFIG"; then
	if grep -q '^DefaultSession=' "$_TD_GDM_CONFIG"; then
		sed -i 's/^DefaultSession=.*/DefaultSession=tuna.desktop/' "$_TD_GDM_CONFIG"
	else
		sed -i '/^\[daemon\]/a DefaultSession=tuna.desktop' "$_TD_GDM_CONFIG"
	fi
else
	mkdir -p "$_TD_GDM_DIR"
	printf '\n[daemon]\nDefaultSession=tuna.desktop\n' >>"$_TD_GDM_CONFIG"
fi
