#!/usr/bin/env bash
# Tuna images must log fresh users straight into the Tuna session, with every
# GDM the Tuna flavors ship (47 on EL10, 48 on trixie, 50 on Fedora 44,
# Ubuntu 26.04 and Tumbleweed, 51 on Arch, Rawhide and sid).
#
# 1. GDM uses the account's AccountsService session before any fallback, and
#    loads it "even if the user doesn't have saved state, as they could have
#    been configured in AccountsService by the administrator" (GDM 47-51
#    daemon/gdm-session-settings.c). AccountsService (>= 22.04.62) fills an
#    account that has no cache file from the first user-templates/<type>
#    found in /run, /etc, then the data dirs (src/user.c
#    user_update_from_template). Tuna's /etc templates set Session=tuna and
#    otherwise keep the distribution's template.
# 2. An account that already has an AccountsService record without a session
#    gets GDM's fallback session: [daemon] FallbackSession on GDM 51
#    (daemon/gdm-session.c get_fallback_session_name, data/gdm.schemas.in),
#    else "gnome" (Ubuntu tries "ubuntu" first), else the first launchable
#    session id in sorted order. GDM has no DefaultSession key.
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

_TD_TEMPLATE_DIR="${_TD_ROOT}/etc/accountsservice/user-templates"
mkdir -p "$_TD_TEMPLATE_DIR"
for _td_type in standard administrator; do
	_td_source="${_TD_ROOT}/usr/share/accountsservice/user-templates/${_td_type}"
	[[ -f "${_TD_TEMPLATE_DIR}/${_td_type}" ]] && _td_source="${_TD_TEMPLATE_DIR}/${_td_type}"
	_td_template="$(cat "$_td_source" 2>/dev/null || true)"
	# Set Session in the [User] group, adding the group or key when missing.
	printf '%s\n' "$_td_template" | awk '
		/^\[/ {
			if (in_user && !done) { print "Session=tuna"; done = 1 }
			in_user = ($0 == "[User]")
			if (in_user) seen = 1
			print
			next
		}
		in_user && /^Session=/ { if (!done) print "Session=tuna"; done = 1; next }
		{ print }
		END {
			if (in_user && !done) print "Session=tuna"
			else if (!seen) print "[User]\nSession=tuna"
		}
	' >"${_TD_TEMPLATE_DIR}/${_td_type}.tmp"
	mv "${_TD_TEMPLATE_DIR}/${_td_type}.tmp" "${_TD_TEMPLATE_DIR}/${_td_type}"
	chmod 0644 "${_TD_TEMPLATE_DIR}/${_td_type}"
done
