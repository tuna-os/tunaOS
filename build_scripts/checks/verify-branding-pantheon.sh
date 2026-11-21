#!/usr/bin/env bash
# Pantheon branding contract: the wallpaper the session and the greeter apply.
#
# WHAT PANTHEON READS
#
#   session   org.gnome.desktop.background picture-uri. No dconf keyfile of
#             ours runs on Pantheon (gurnard ships no /etc/dconf/profile), so
#             the compiled schema default decides, and elementary-default-
#             settings ships its own override naming elementary's wallpaper.
#             zzzz-tunaos.gschema.override has to sort last and win.
#   greeter   io.elementary.greeter draws the selected account's synced
#             wallpaper (/var/lib/lightdm-data/<user>/wallpaper/) and, with no
#             account yet, the fixed path /usr/share/backgrounds/elementaryos-
#             default (strings in io.elementary.greeter 8.1.2, gurnard:pantheon
#             263de4c818f4: "BackgroundImage.vala:19: Fallback to default
#             wallpaper"). That image ships no such file, so the first-boot
#             greeter has no wallpaper at all.
#
# Configuration evidence only, like verify-branding-gnome.sh: this reads what
# Pantheon will load, it does not prove pixels.
#
# USAGE
#   verify-branding-pantheon.sh <canonical-variant> [--runtime]
# TUNAOS_BRANDING_ROOT prefixes every image path for tests.

set -uo pipefail

variant="${1:?usage: verify-branding-pantheon.sh <canonical-variant> [--runtime]}"
mode="${2:-build}"
R="${TUNAOS_BRANDING_ROOT:-}"
fails=0
marker_emitted=0
workspace=""
finish() {
	local rc=$?
	[[ -z "$workspace" ]] || rm -rf -- "$workspace"
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		echo "TUNAOS_BRANDING_PANTHEON_FAIL variant=${variant} reason=early_exit rc=${rc}" | tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap finish EXIT
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg
WANT_URI="'file://${WALLPAPER}'"

# select-wallpaper.sh's precedence: <variant>-<desktop>.jpg, then <variant>.jpg.
canonical=""
for candidate in "${variant}-pantheon.jpg" "${variant}.jpg"; do
	if [[ -f "${R}/usr/share/backgrounds/tunaos/${candidate}" ]]; then
		canonical="/usr/share/backgrounds/tunaos/${candidate}"
		break
	fi
done
echo "== pantheon wallpaper =="
if [[ -z "$canonical" ]]; then
	fail "no canonical wallpaper for variant=${variant} (${variant}-pantheon.jpg or ${variant}.jpg)"
elif ! cmp -s "${R}${WALLPAPER}" "${R}${canonical}"; then
	fail "${WALLPAPER} is not the bytes of ${canonical}"
else
	pass "${WALLPAPER} = ${canonical}"
fi

# Effective session default: a system dconf value when one is compiled,
# otherwise the compiled schema default. Read it as the session reads it:
# with XDG_CURRENT_DESKTOP=Pantheon, which gala and
# io.elementary.greeter-compositor (compositor/main.vala:34) both set.
# elementary-default-settings ships [org.gnome.desktop.background:Pantheon]
# (default-settings.gschema.override:7), and a desktop-qualified section beats
# every plain one whatever the file order. Without the variable gsettings
# answers with zzzz-tunaos's plain section, which is a false pass: measured on
# gurnard:pantheon 263de4c818f4, picture-uri reads elementaryos-default and
# picture-uri-dark reads 'file://' in the session's context.
workspace="$(mktemp -d)" || exit 1
mkdir -p "$workspace/home" "$workspace/runtime"
chmod 0700 "$workspace/runtime"
have_gsettings=true
command -v gsettings >/dev/null 2>&1 || {
	have_gsettings=false
	fail "gsettings is required to read the compiled schema default"
}
have_dconf=false
command -v dconf >/dev/null 2>&1 && [[ -f "${R}/etc/dconf/profile/user" ]] && have_dconf=true
for key in picture-uri picture-uri-dark; do
	schema_default=""
	if [[ "$have_gsettings" == true ]]; then
		schema_default="$(env -i PATH="$PATH" HOME="$workspace/home" XDG_RUNTIME_DIR="$workspace/runtime" \
			XDG_CURRENT_DESKTOP=Pantheon GSETTINGS_BACKEND=memory XDG_DATA_DIRS="${R}/usr/local/share:${R}/usr/share" \
			gsettings get org.gnome.desktop.background "$key" 2>/dev/null || true)"
	fi
	dconf_value=""
	if [[ "$have_dconf" == true ]]; then
		dconf_value="$(HOME="$workspace/home" XDG_CONFIG_HOME="$workspace/home/.config" XDG_RUNTIME_DIR="$workspace/runtime" \
			DCONF_PROFILE="${R}/etc/dconf/profile/user" dconf read "/org/gnome/desktop/background/${key}" 2>/dev/null || true)"
	fi
	effective="${dconf_value:-$schema_default}"
	if [[ "$effective" == "$WANT_URI" ]]; then
		pass "session ${key}=${effective} (${dconf_value:+dconf}${dconf_value:-schema default as Pantheon})"
	else
		fail "session ${key}=${effective:-unset}, want ${WANT_URI} (schema default as Pantheon=${schema_default:-unset} dconf=${dconf_value:-unset})"
	fi
done

echo "== pantheon greeter =="
fallback=/usr/share/backgrounds/elementaryos-default
if [[ ! -e "${R}${fallback}" ]]; then
	fail "greeter fallback ${fallback} is absent: the no-account greeter draws no wallpaper (want the bytes of ${WALLPAPER})"
elif ! cmp -s "${R}${fallback}" "${R}${WALLPAPER}"; then
	fail "greeter fallback ${fallback} is not the variant wallpaper"
else
	pass "greeter fallback ${fallback} = ${WALLPAPER}"
fi
# Per-account synced copies exist once a user has logged in; each must be the
# variant's unless that user chose their own picture (a file under /home).
for synced in "${R}"/var/lib/lightdm-data/*/wallpaper/*; do
	[[ -f "$synced" ]] || continue
	if cmp -s "$synced" "${R}${WALLPAPER}"; then
		pass "greeter copy ${synced#"$R"} = variant wallpaper"
	else
		echo "  note: greeter copy ${synced#"$R"} differs from the variant wallpaper (the account's own choice)"
	fi
done

if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_BRANDING_PANTHEON_FAIL variant=${variant} failures=${fails}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_PANTHEON_OK variant=${variant} scope=configuration rendered=not-run" | tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
