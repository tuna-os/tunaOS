#!/usr/bin/env bash
# Configure GDM for the Tuna Desktop experience.
#
# The hook is sourced by install-desktop.sh after the requested packages are
# installed and before the experience files are copied. It therefore reads the
# theme source from the build context, while the static GDM configuration and
# source CSS are applied by the normal experience overlay immediately after.

set -euo pipefail

tuna_gdm_fail() {
	echo "tuna-gdm: $*" >&2
	return 1
}

_tuna_gdm_unit=""
for _tuna_gdm_candidate in \
	/usr/lib/systemd/system/gdm.service \
	/lib/systemd/system/gdm.service \
	/usr/lib/systemd/system/gdm3.service \
	/lib/systemd/system/gdm3.service; do
	if [[ -f "$_tuna_gdm_candidate" ]]; then
		_tuna_gdm_unit="$_tuna_gdm_candidate"
		break
	fi
done
[[ -n "$_tuna_gdm_unit" ]] || tuna_gdm_fail "neither gdm.service nor gdm3.service is installed"

[[ -f /usr/share/wayland-sessions/tuna.desktop ]] ||
	tuna_gdm_fail "the Tuna Wayland session is missing"

_tuna_gdm_theme="${_TD_CTX:-/run/context}/experiences/tuna/files/usr/share/gnome-shell/theme/tuna-gdm.css"
[[ -f "$_tuna_gdm_theme" ]] || tuna_gdm_fail "theme source is missing: $_tuna_gdm_theme"
command -v gresource >/dev/null 2>&1 || tuna_gdm_fail "gresource is required to update the GDM theme"
command -v glib-compile-resources >/dev/null 2>&1 ||
	tuna_gdm_fail "glib-compile-resources is required to update the GDM theme"

_tuna_gdm_name="${_tuna_gdm_unit##*/}"
_tuna_gdm_name="${_tuna_gdm_name%.service}"
_tuna_gdm_mask="/etc/systemd/system/${_tuna_gdm_name}.service"
if [[ "$(readlink "$_tuna_gdm_mask" 2>/dev/null || true)" == "/dev/null" ]]; then
	rm -f "$_tuna_gdm_mask"
fi

# A Tuna image has one display manager. Mask stale greetd state even when the
# package came from a base image, and remove its old wants-link before GDM is
# enabled. The symlink is the offline equivalent of `systemctl mask`.
mkdir -p /etc/systemd/system/graphical.target.wants
rm -f /etc/systemd/system/graphical.target.wants/greetd.service
ln -sfn /dev/null /etc/systemd/system/greetd.service
rm -f \
	/etc/greetd/config.toml \
	/etc/greetd/environments \
	/etc/greetd/gtkgreet.css \
	/usr/bin/Tuna \
	/usr/libexec/tunaos/greetd-session

# Make the selected GDM the only unit pulled in by graphical.target and the
# display-manager alias. The manifest's common installer does the same for
# normal paths; force it here because this hook is the Tuna cutover boundary.
rm -f "/etc/systemd/system/graphical.target.wants/${_tuna_gdm_name}.service"
ln -sfn "$_tuna_gdm_unit" "/etc/systemd/system/graphical.target.wants/${_tuna_gdm_name}.service"
rm -f /etc/systemd/system/display-manager.service
ln -sfn "$_tuna_gdm_unit" /etc/systemd/system/display-manager.service
systemctl set-default graphical.target

# GNOME Shell owns the GDM login UI in a compiled GResource. Extract the
# distro resource, append the Tuna overrides to every shell stylesheet, and
# compile the resource back in place so the config works across GNOME versions.
_tuna_gdm_resource=""
for _tuna_gdm_candidate in \
	/usr/share/gnome-shell/gnome-shell-theme.gresource \
	/usr/lib/gnome-shell/gnome-shell-theme.gresource; do
	if [[ -f "$_tuna_gdm_candidate" ]]; then
		_tuna_gdm_resource="$_tuna_gdm_candidate"
		break
	fi
done
[[ -n "$_tuna_gdm_resource" ]] || tuna_gdm_fail "GNOME Shell theme resource is missing"

_tuna_gdm_tmp="$(mktemp -d)"
_tuna_gdm_xml="$_tuna_gdm_tmp/theme.gresource.xml"
_tuna_gdm_output="$_tuna_gdm_tmp/gnome-shell-theme.gresource"
_tuna_gdm_css_count=0
mapfile -t _tuna_gdm_resources < <(gresource list "$_tuna_gdm_resource")
((${#_tuna_gdm_resources[@]} > 0)) || tuna_gdm_fail "GDM theme resource is empty"

{
	printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>'
	printf '%s\n' '<gresources>'
	printf '%s\n' '  <gresource prefix="/org/gnome/shell/theme">'
	for _tuna_gdm_resource_name in "${_tuna_gdm_resources[@]}"; do
		_tuna_gdm_relative="${_tuna_gdm_resource_name#/org/gnome/shell/theme/}"
		[[ "$_tuna_gdm_relative" != "$_tuna_gdm_resource_name" ]] || continue
		_tuna_gdm_path="$_tuna_gdm_tmp/$_tuna_gdm_relative"
		mkdir -p "$(dirname "$_tuna_gdm_path")"
		gresource extract "$_tuna_gdm_resource" "$_tuna_gdm_resource_name" >"$_tuna_gdm_path"
		case "$_tuna_gdm_relative" in
		gnome-shell*.css|*/gnome-shell*.css)
			printf '\n' >>"$_tuna_gdm_path"
			cat "$_tuna_gdm_theme" >>"$_tuna_gdm_path"
			_tuna_gdm_css_count=$((_tuna_gdm_css_count + 1))
			;;
		esac
		printf '    <file>%s</file>\n' "$_tuna_gdm_relative"
	done
	printf '%s\n' '  </gresource>'
	printf '%s\n' '</gresources>'
} >"$_tuna_gdm_xml"

(( _tuna_gdm_css_count > 0 )) || tuna_gdm_fail "GNOME Shell theme resource has no stylesheet"
glib-compile-resources "$_tuna_gdm_xml" \
	--sourcedir="$_tuna_gdm_tmp" \
	--target="$_tuna_gdm_output"
install -m0644 "$_tuna_gdm_output" "$_tuna_gdm_resource"
rm -rf "$_tuna_gdm_tmp"

echo "tuna-gdm: selected ${_tuna_gdm_name}, updated ${_tuna_gdm_css_count} GNOME Shell stylesheet(s)"
