#!/usr/bin/env bash
# Verify canonical asset bytes and fresh-profile compiled GNOME defaults.
# This is configuration evidence, NOT proof of a rendered greeter/session.
# Tests may prefix image paths with TUNAOS_BRANDING_ROOT and select the database
# directory with TUNAOS_DCONF_DB. No user settings are written or reset.
set -uo pipefail

variant="${1:?usage: verify-branding-gnome.sh <canonical-variant> [--runtime]}"
mode="${2:-build}"
asset_root="${TUNAOS_BRANDING_ROOT:-}"
db_root="${TUNAOS_DCONF_DB:-${asset_root}/etc/dconf/db}"
fails=0
marker_emitted=0
workspace=""
finish() {
	local rc=$?
	[[ -z "$workspace" ]] || rm -rf -- "$workspace"
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		echo "TUNAOS_BRANDING_GNOME_FAIL variant=${variant} reason=early_exit rc=${rc}" |
			tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap finish EXIT
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

identity="${asset_root}/usr/share/tunaos/identity.env"
canonical="$(awk -F"'" '$1 == "TUNAOS_VARIANT=" {print $2; exit}' "$identity" 2>/dev/null)"
if [[ ! "$canonical" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ || "$canonical" != "$variant" ]]; then
	fail "canonical variant=${canonical:-missing} does not match requested variant=${variant}; display/publish names are not identity"
fi

# Compare bytes, not names: a sibling's valid SVG at the selected path fails.
# Identical/shared assets remain valid; uniqueness of a fish mark is not required.
check_asset() {
	local selected="$1" expected="$2" surface="$3"
	if [[ ! -f "${asset_root}${selected}" ]]; then
		fail "${surface} names '${selected}', which is not in the image"
	elif [[ ! -f "${asset_root}${expected}" ]]; then
		fail "canonical ${surface} asset missing: ${expected}"
	elif ! cmp -s "${asset_root}${selected}" "${asset_root}${expected}"; then
		fail "${surface} bytes differ from canonical ${expected}"
	else
		pass "${surface} canonical_asset=${expected} sha256=$(sha256sum "${asset_root}${expected}" | cut -d' ' -f1)"
	fi
}

# Match select-wallpaper.sh's declared desktop > anime > scene precedence.
# Tuna shares GDM only; GNOME wallpaper keys do not qualify its session.
desktop="${TUNAOS_BRANDING_DESKTOP:-gnome}"
wallpaper=""
scope="compiled-defaults"
wallpaper_status="compiled-defaults"
if [[ "$desktop" != tuna ]]; then
	for candidate in "${canonical}-${desktop}.jpg" "${canonical}-anime.jpg" "${canonical}.jpg"; do
		if [[ -f "${asset_root}/usr/share/backgrounds/tunaos/${candidate}" ]]; then
			wallpaper="/usr/share/backgrounds/tunaos/${candidate}"
			break
		fi
	done
	[[ -n "$wallpaper" ]] || fail "no canonical wallpaper for variant=${canonical} desktop=${desktop}"
else
	scope="compiled-greeter"
	wallpaper_status="not-run"
fi

# Read the compiled databases through the profiles GNOME/GDM use. Isolate the
# user database in a private HOME so old users' explicit choices are untouched.
# file-db lets fixtures exercise real dconf blobs without host /etc mutation.
workspace="$(mktemp -d)" || exit 1
mkdir -p "$workspace/home" "$workspace/config" "$workspace/cache" "$workspace/runtime"
chmod 0700 "$workspace/runtime"
read_default() {
	local profile_name="$1" schema="$2" key="$3" profile compiled db entry
	profile="${asset_root}/etc/dconf/profile/${profile_name}"
	[[ -f "$profile" ]] || profile="${asset_root}/usr/share/dconf/profile/${profile_name}"
	if [[ ! -f "$profile" ]]; then
		fail "missing ${profile_name} dconf profile" >&2
		return 1
	fi
	db=local
	[[ "$profile_name" != gdm ]] || db=gdm
	if ! grep -qx "system-db:${db}" "$profile"; then
		fail "${profile_name} profile does not consume system-db:${db}" >&2
		return 1
	fi
	compiled="$workspace/${profile_name}.profile"
	: >"$compiled"
	while IFS= read -r entry || [[ -n "$entry" ]]; do
		case "$entry" in
		system-db:*) printf 'file-db:%s/%s\n' "$db_root" "${entry#system-db:}" ;;
		file-db:/*) printf 'file-db:%s%s\n' "$asset_root" "${entry#file-db:}" ;;
		*) printf '%s\n' "$entry" ;;
		esac
	done <"$profile" >"$compiled"
	if [[ ! -s "${db_root}/${db}" ]]; then
		fail "missing compiled ${db} database (run dconf update)" >&2
		return 1
	fi
	HOME="$workspace/home" XDG_CONFIG_HOME="$workspace/config" XDG_CACHE_HOME="$workspace/cache" \
		XDG_RUNTIME_DIR="$workspace/runtime" DCONF_PROFILE="$compiled" GSETTINGS_BACKEND=dconf \
		gsettings get "$schema" "$key"
}

if ! command -v gsettings >/dev/null 2>&1; then
	fail "gsettings is required for compiled consumer readback"
else
	if [[ "$desktop" != tuna ]]; then
		for key in picture-uri picture-uri-dark; do
			if value="$(read_default user org.gnome.desktop.background "$key")"; then
				if [[ "$value" != "'file:///usr/share/backgrounds/tunaos/tunaos-default.jpg'" ]]; then
					fail "compiled ${key}=${value}; fresh default does not select the canonical wallpaper alias"
				else
					check_asset /usr/share/backgrounds/tunaos/tunaos-default.jpg "$wallpaper" "$key"
				fi
			else
				fail "cannot read compiled fresh default ${key}"
			fi
		done
	fi
	if value="$(read_default gdm org.gnome.login-screen logo)"; then
		if [[ "$value" != \'/*\' ]]; then
			fail "compiled login-screen logo is not an absolute asset path: ${value}"
		else
			value="${value#\'}"
			value="${value%\'}"
			check_asset "$value" "/usr/share/tunaos/lettermarks/${canonical}.svg" login-screen-logo
		fi
	else
		fail "cannot read compiled GDM login-screen logo"
	fi
fi

if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_BRANDING_GNOME_FAIL variant=${variant} failures=${fails}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_GNOME_OK variant=${variant} scope=${scope} rendered=not-run existing_user=not-modified wallpaper=${wallpaper_status}" |
	tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
