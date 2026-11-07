#!/usr/bin/env bash
# GDM 47/48/50 need inherited Session=tuna: their fallback prefers GNOME even
# when its chooser entry is hidden. GDM 51 supports daemon/FallbackSession.
# There, explicit empty Session= lets a real first login change the inherited
# value to tuna and stock AccountsService persist it (native run 41215443626
# showed inherited tuna -> tuna left no record). See docs/ci-troubleshooting.md.
# Only templates change; existing per-user AccountsService records stay intact.
set -euo pipefail

_TD_ROOT="${TUNAOS_GDM_DEFAULT_ROOT:-}"
_TD_GDM_DIR="${_TD_ROOT}/etc/gdm"
[[ -d "${_TD_ROOT}/etc/gdm3" ]] && _TD_GDM_DIR="${_TD_ROOT}/etc/gdm3"
_TD_GDM_CONFIG="${_TD_GDM_DIR}/custom.conf"

_TD_GDM_BINARY=""
if [[ -n "$_TD_ROOT" ]]; then
	for _td_binary in /usr/sbin/gdm /usr/bin/gdm /usr/sbin/gdm3 /usr/bin/gdm3; do
		if [[ -x "${_TD_ROOT}${_td_binary}" ]]; then
			_TD_GDM_BINARY="${_TD_ROOT}${_td_binary}"
			break
		fi
	done
else
	_TD_GDM_BINARY="$(command -v gdm || command -v gdm3 || true)"
fi
_td_version="$("$_TD_GDM_BINARY" --version 2>/dev/null)" || _td_version=""
_TD_SESSION=tuna
if [[ "$_td_version" =~ ^[Gg][Dd][Mm]3?[[:space:]]+([0-9]+)\.[0-9]+([.-][0-9A-Za-z.-]+)?[[:space:]]*$ ]] &&
	((10#${BASH_REMATCH[1]} >= 51)) &&
	grep -aFq 'daemon/FallbackSession' "$_TD_GDM_BINARY"; then
	_TD_SESSION=""
fi

mkdir -p "$_TD_GDM_DIR"
_td_config_source="$_TD_GDM_CONFIG"
[[ -f "$_td_config_source" ]] || _td_config_source=/dev/null
# Scope the real fallback to [daemon]; DefaultSession was never a GDM key.
awk '
	/^DefaultSession=/ { next }
	/^\[/ {
		if (in_daemon && !done) { print "FallbackSession=tuna"; done = 1 }
		in_daemon = ($0 == "[daemon]")
		if (in_daemon) seen = 1
		print
		next
	}
	in_daemon && /^FallbackSession=/ { if (!done) print "FallbackSession=tuna"; done = 1; next }
	{ print }
	END {
		if (in_daemon && !done) print "FallbackSession=tuna"
		else if (!seen) print "[daemon]\nFallbackSession=tuna"
	}
' "$_td_config_source" >"${_TD_GDM_CONFIG}.tmp"
mv "${_TD_GDM_CONFIG}.tmp" "$_TD_GDM_CONFIG"

_TD_TEMPLATE_DIR="${_TD_ROOT}/etc/accountsservice/user-templates"
mkdir -p "$_TD_TEMPLATE_DIR"
for _td_type in standard administrator; do
	_td_source=""
	for _td_dir in /etc /usr/local/share /usr/share; do
		if [[ -f "${_TD_ROOT}${_td_dir}/accountsservice/user-templates/${_td_type}" ]]; then
			_td_source="${_TD_ROOT}${_td_dir}/accountsservice/user-templates/${_td_type}"
			break
		fi
	done
	_td_template="$(cat "$_td_source" 2>/dev/null || true)"
	# Set Session in the [User] group, adding the group or key when missing.
	printf '%s\n' "$_td_template" | awk -v session="$_TD_SESSION" '
		/^\[/ {
			if (in_user && !done) { print "Session=" session; done = 1 }
			in_user = ($0 == "[User]")
			if (in_user) seen = 1
			print
			next
		}
		in_user && /^Session=/ { if (!done) print "Session=" session; done = 1; next }
		{ print }
		END {
			if (in_user && !done) print "Session=" session
			else if (!seen) print "[User]\nSession=" session
		}
	' >"${_TD_TEMPLATE_DIR}/${_td_type}.tmp"
	mv "${_TD_TEMPLATE_DIR}/${_td_type}.tmp" "${_TD_TEMPLATE_DIR}/${_td_type}"
	chmod 0644 "${_TD_TEMPLATE_DIR}/${_td_type}"
done
