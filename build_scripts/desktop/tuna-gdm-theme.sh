#!/usr/bin/env bash

# Tuna's GDM greeter uses GNOME Shell's packaged stylesheet. Keep that upstream
# stylesheet intact and layer the variant accent through GLib's resource overlay.
_tuna_gdm_theme_extract() {
	# GJS is part of GNOME Shell's runtime; use GIO directly instead of adding
	# a development-only GResource command to the finished image.
	TUNAOS_GRESOURCE_FILE="$1" TUNAOS_GRESOURCE_PATH="$2" gjs -c '
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const ByteArray = imports.byteArray;
const resource = Gio.Resource.load(GLib.getenv("TUNAOS_GRESOURCE_FILE"));
const bytes = resource.lookup_data(
    GLib.getenv("TUNAOS_GRESOURCE_PATH"),
    Gio.ResourceLookupFlags.NONE
);
print(ByteArray.toString(bytes.get_data()));
'
}

_tuna_gdm_theme_install() {
	local test_root="${TUNAOS_GDM_THEME_ROOT:-}"
	local resource_file="${test_root}/usr/share/gnome-shell/gnome-shell-theme.gresource"
	local theme_dir="${test_root}/usr/share/tunaos/gdm-theme"
	local identity_file="${test_root}/usr/share/tunaos/identity.env"
	local gdm_unit="gdm"
	local accent stylesheet resource_path unit_dir

	if [[ -n "$test_root" ]]; then
		if [[ -f "$test_root/usr/lib/systemd/system/gdm3.service" || -f "$test_root/lib/systemd/system/gdm3.service" ]]; then
			gdm_unit="gdm3"
		fi
		unit_dir="${test_root}/etc/systemd/system/${gdm_unit}.service.d"
	else
		resource_file="/usr/share/gnome-shell/gnome-shell-theme.gresource"
		theme_dir="/usr/share/tunaos/gdm-theme"
		identity_file="/usr/share/tunaos/identity.env"
		if [[ -f /usr/lib/systemd/system/gdm3.service || -f /lib/systemd/system/gdm3.service ]]; then
			gdm_unit="gdm3"
		fi
		unit_dir="/etc/systemd/system/${gdm_unit}.service.d"
	fi

	[[ -r "$identity_file" ]] || {
		echo "Tuna variant identity is missing: $identity_file" >&2
		return 1
	}
	accent="$(awk -F"'" '$1 == "TUNAOS_ACCENT=" { print $2; exit }' "$identity_file")"
	[[ "$accent" =~ ^#[[:xdigit:]]{6}$ ]] || {
		echo "Tuna variant accent is invalid in $identity_file: ${accent:-unset}" >&2
		return 1
	}
	[[ -r "$resource_file" ]] || {
		echo "GNOME Shell theme resource is missing: $resource_file" >&2
		return 1
	}

	command -v gjs >/dev/null 2>&1 || {
		echo "gjs is required to theme the GDM greeter" >&2
		return 1
	}
	mkdir -p "$theme_dir" "$unit_dir"

	for stylesheet in gnome-shell-dark.css gnome-shell-light.css gnome-shell-high-contrast.css; do
		resource_path="/org/gnome/shell/theme/$stylesheet"
		if ! _tuna_gdm_theme_extract "$resource_file" "$resource_path" >"$theme_dir/$stylesheet"; then
			rm -f "$theme_dir/$stylesheet"
			echo "GNOME Shell theme resource does not contain $resource_path" >&2
			return 1
		fi
		cat >>"$theme_dir/$stylesheet" <<CSS

/* Tuna's per-variant identity accent. */
#lockDialogGroup {
  background-color: ${accent};
}
CSS
	done

	cat >"$unit_dir/10-tuna-gdm-theme.conf" <<'UNIT'
[Service]
Environment=G_RESOURCE_OVERLAYS=/org/gnome/shell/theme=/usr/share/tunaos/gdm-theme
UNIT
}

_tuna_gdm_theme_install
