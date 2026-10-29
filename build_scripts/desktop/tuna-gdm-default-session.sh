#!/usr/bin/env bash
# Tuna images must log fresh users straight into the Tuna session. A user with
# no saved session gets GDM's fallback session, which is "gnome" unless
# [daemon] FallbackSession names another session id (GDM 51.1
# daemon/gdm-session.c get_fallback_session_name, key daemon/FallbackSession
# in data/gdm.schemas.in). GDM has no DefaultSession key; it ignores one.
# GDM before 51 has no FallbackSession key and always falls back to "gnome".
set -euo pipefail

_TD_ROOT="${TUNAOS_GDM_DEFAULT_ROOT:-}"
_TD_GDM_DIR="${_TD_ROOT}/etc/gdm"
[[ -d "${_TD_ROOT}/etc/gdm3" ]] && _TD_GDM_DIR="${_TD_ROOT}/etc/gdm3"
_TD_GDM_CONFIG="${_TD_GDM_DIR}/custom.conf"

if [[ -f "$_TD_GDM_CONFIG" ]]; then
	# Drop the key GDM never read so the file states only what takes effect.
	sed -i '/^DefaultSession=/d' "$_TD_GDM_CONFIG"
fi
if [[ -f "$_TD_GDM_CONFIG" ]] && grep -q '^\[daemon\]' "$_TD_GDM_CONFIG"; then
	if grep -q '^FallbackSession=' "$_TD_GDM_CONFIG"; then
		sed -i 's/^FallbackSession=.*/FallbackSession=tuna/' "$_TD_GDM_CONFIG"
	else
		sed -i '/^\[daemon\]/a FallbackSession=tuna' "$_TD_GDM_CONFIG"
	fi
else
	mkdir -p "$_TD_GDM_DIR"
	printf '\n[daemon]\nFallbackSession=tuna\n' >>"$_TD_GDM_CONFIG"
fi
