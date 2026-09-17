#!/usr/bin/env bash
# GNOME branding contract — asserts the APPLIED state, not the assets.
#
# WHY GNOME NEEDS ITS OWN
#
# verify-branding.sh asks whether the wallpaper FILE exists. On marlin:gnome it
# did, at 309864 bytes, alongside the logo at 4742 bytes and a plymouth symlink
# — and the session showed Arch's stock background, because nothing in the image
# named any of them. The cell was green the whole time.
#
# A file under /usr/share/backgrounds is not branding. The thing a GNOME session
# reads is dconf, so that is what this asserts:
#
#   * some keyfile under /etc/dconf/db/local.d sets picture-uri
#   * the URI it sets resolves to a file that is actually present
#   * the `local` database is compiled, or the keyfile is inert
#   * the greeter has its own logo, in gdm.d, because it reads a different
#     database and a logo set only in `local` never reaches the login screen
#
# It deliberately does NOT look for our keyfile by name. Any mechanism that
# leaves the session branded should pass; the contract is on the state, not on
# gnome-set-branding.sh having run. See docs/BRANDING.md.
#
# USAGE
#   verify-branding-gnome.sh <variant> [--runtime]
#
# TUNAOS_DCONF_DB overrides the database root and TUNAOS_BRANDING_ROOT prefixes
# the asset paths a keyfile names. Both exist so the tests can build a fixture
# tree; builds set neither, and the defaults are the real image paths.

set -uo pipefail

variant="${1:?usage: verify-branding-gnome.sh <variant> [--runtime]}"
mode="${2:-build}"
db_root="${TUNAOS_DCONF_DB:-/etc/dconf/db}"
asset_root="${TUNAOS_BRANDING_ROOT:-}"

marker_emitted=0
emit_fail_on_early_exit() {
	local rc=$?
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		echo "TUNAOS_BRANDING_GNOME_FAIL variant=${variant} reason=early_exit rc=${rc}" |
			tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap emit_fail_on_early_exit EXIT

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

# The value of the first picture-uri in a keyfile directory, without the
# file:// prefix. Empty when no keyfile sets one.
wallpaper_uri() {
	local dir="$1" line
	line="$(grep -rhoE "^picture-uri[[:space:]]*=[[:space:]]*'[^']+'" "$dir" 2>/dev/null | head -1)"
	[[ -z "$line" ]] && return 0
	line="${line#*\'}"
	line="${line%\'}"
	printf '%s' "${line#file://}"
}

echo "== gnome wallpaper =="
uri="$(wallpaper_uri "${db_root}/local.d")"
if [[ -z "$uri" ]]; then
	fail "no keyfile under ${db_root}/local.d sets picture-uri — the session shows the upstream wallpaper"
else
	pass "picture-uri=${uri}"
	# A key naming a missing file renders as a black desktop, which reads as a
	# broken image rather than an unbranded one.
	if [[ -e "${asset_root}${uri}" ]]; then
		pass "wallpaper file exists"
	else
		fail "picture-uri names '${uri}', which is not in the image"
	fi
	# Dark style is a separate key. Setting only the light one leaves a dark
	# session on the distro default, which is half the users.
	if grep -rqE "^picture-uri-dark[[:space:]]*=" "${db_root}/local.d" 2>/dev/null; then
		pass "picture-uri-dark set"
	else
		fail "picture-uri-dark is unset — a dark-style session keeps the upstream wallpaper"
	fi
fi

echo "== gnome greeter =="
if grep -rqE "^logo[[:space:]]*=" "${db_root}/gdm.d" 2>/dev/null; then
	logo="$(grep -rhoE "^logo[[:space:]]*=[[:space:]]*'[^']+'" "${db_root}/gdm.d" 2>/dev/null | head -1)"
	logo="${logo#*\'}"
	logo="${logo%\'}"
	pass "login-screen logo=${logo}"
	if [[ -e "${asset_root}${logo}" ]]; then
		pass "logo file exists"
	else
		fail "login-screen logo names '${logo}', which is not in the image"
	fi
else
	fail "no keyfile under ${db_root}/gdm.d sets the login-screen logo"
fi

# A keyfile nothing compiled is a keyfile nothing reads.
echo "== compiled =="
for db in local gdm; do
	if [[ -d "${db_root}/${db}.d" ]]; then
		if [[ -s "${db_root}/${db}" ]]; then
			pass "${db} compiled"
		else
			fail "${db_root}/${db}.d has keyfiles but ${db_root}/${db} is missing or empty (run dconf update)"
		fi
	fi
done

echo
if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_BRANDING_GNOME_FAIL variant=${variant} failures=${fails}" |
		tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_GNOME_OK variant=${variant}" | tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
