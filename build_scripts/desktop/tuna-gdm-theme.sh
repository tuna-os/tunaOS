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
	local shell_desktop="${test_root}/usr/share/applications/org.gnome.Shell.desktop"
	local greeter_apps_dir="${test_root}/usr/share/gdm/greeter/applications"
	local accent stylesheet resource_path staged_theme greeter_desktop_tmp

	if [[ -z "$test_root" ]]; then
		resource_file="/usr/share/gnome-shell/gnome-shell-theme.gresource"
		theme_dir="/usr/share/tunaos/gdm-theme"
		identity_file="/usr/share/tunaos/identity.env"
		shell_desktop="/usr/share/applications/org.gnome.Shell.desktop"
		greeter_apps_dir="/usr/share/gdm/greeter/applications"
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
	[[ -r "$shell_desktop" ]] || {
		echo "GNOME Shell session component is missing: $shell_desktop" >&2
		return 1
	}
	command -v gjs >/dev/null 2>&1 || {
		echo "gjs is required to theme the GDM greeter" >&2
		return 1
	}

	mkdir -p "${theme_dir%/*}" "$greeter_apps_dir"
	staged_theme="$(mktemp -d "${theme_dir}.tmp.XXXXXX")"
	for stylesheet in gnome-shell-dark.css gnome-shell-light.css gnome-shell-high-contrast.css; do
		resource_path="/org/gnome/shell/theme/$stylesheet"
		if ! _tuna_gdm_theme_extract "$resource_file" "$resource_path" >"$staged_theme/$stylesheet"; then
			rm -rf "$staged_theme"
			echo "GNOME Shell theme resource does not contain $resource_path" >&2
			return 1
		fi
		cat >>"$staged_theme/$stylesheet" <<CSS

/* Tuna's per-variant identity accent. */
#lockDialogGroup {
  background-color: ${accent};
}
CSS
	done
	rm -rf "$theme_dir"
	mv "$staged_theme" "$theme_dir"

	# GDM puts /usr/share/gdm/greeter first in the greeter's XDG_DATA_DIRS.
	# Shadow only its GNOME Shell session component so regular user sessions do
	# not inherit the resource overlay.
	greeter_desktop_tmp="$(mktemp "${greeter_apps_dir}/.org.gnome.Shell.desktop.XXXXXX")"
	if ! awk '
		BEGIN { replaced = 0 }
		/^Exec=/ && !replaced {
			sub(/^Exec=/, "Exec=env G_RESOURCE_OVERLAYS=/org/gnome/shell/theme=/usr/share/tunaos/gdm-theme ")
			replaced = 1
		}
		{ print }
		END { if (!replaced) exit 1 }
	' "$shell_desktop" >"$greeter_desktop_tmp"; then
		rm -f "$greeter_desktop_tmp"
		echo "GNOME Shell session component has no Exec entry: $shell_desktop" >&2
		return 1
	fi
	mv "$greeter_desktop_tmp" "$greeter_apps_dir/org.gnome.Shell.desktop"
}

_tuna_gdm_theme_install
