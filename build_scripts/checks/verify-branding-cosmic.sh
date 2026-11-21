#!/usr/bin/env bash
# COSMIC branding contract: the background cosmic-bg and the greeter apply.
#
# WHAT COSMIC READS
#
#   session   cosmic-config: ~/.config/cosmic/com.system76.CosmicBackground/v1/all
#             when the user has one, else the system default under
#             /usr/share/cosmic/. cosmic-bg's package ships that default naming
#             the stock wallpaper; cosmic-set-branding.sh rewrites it after the
#             install (docs/BRANDING.md).
#   greeter   cosmic-greeter draws each account's own background config and
#             the same system default when none exists. Where greetd runs
#             gtkgreet instead (the fallback greeter, greetd-gtkgreet.sh), the
#             background is /etc/greetd/gtkgreet.css.
#
# Configuration evidence only; it does not prove pixels.
#
# USAGE
#   verify-branding-cosmic.sh <canonical-variant> [--runtime]
# TUNAOS_BRANDING_ROOT prefixes every image path for tests.

set -uo pipefail

variant="${1:?usage: verify-branding-cosmic.sh <canonical-variant> [--runtime]}"
mode="${2:-build}"
R="${TUNAOS_BRANDING_ROOT:-}"
fails=0
marker_emitted=0
finish() {
	local rc=$?
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		echo "TUNAOS_BRANDING_COSMIC_FAIL variant=${variant} reason=early_exit rc=${rc}" | tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap finish EXIT
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg
BG_CONFIG=com.system76.CosmicBackground/v1/all

cosmic_bg_source() { # <config file>
	sed -n 's/.*source:[[:space:]]*Path("\([^"]*\)").*/\1/p' "$1" 2>/dev/null | head -1
}

canonical=""
for candidate in "${variant}-cosmic.jpg" "${variant}.jpg"; do
	if [[ -f "${R}/usr/share/backgrounds/tunaos/${candidate}" ]]; then
		canonical="/usr/share/backgrounds/tunaos/${candidate}"
		break
	fi
done
echo "== cosmic wallpaper =="
if [[ -z "$canonical" ]]; then
	fail "no canonical wallpaper for variant=${variant} (${variant}-cosmic.jpg or ${variant}.jpg)"
elif ! cmp -s "${R}${WALLPAPER}" "${R}${canonical}"; then
	fail "${WALLPAPER} is not the bytes of ${canonical}"
else
	pass "${WALLPAPER} = ${canonical}"
fi

system_default="${R}/usr/share/cosmic/${BG_CONFIG}"
src="$(cosmic_bg_source "$system_default")"
if [[ ! -f "$system_default" ]]; then
	fail "no cosmic-bg system default at /usr/share/cosmic/${BG_CONFIG}"
elif [[ "$src" != "$WALLPAPER" ]]; then
	fail "cosmic-bg system default source=${src:-unparsable}, want ${WALLPAPER}"
else
	pass "cosmic-bg system default source=${src}"
fi

echo "== cosmic greeter =="
dm="$(basename "$(readlink "${R}/etc/systemd/system/display-manager.service" 2>/dev/null)" 2>/dev/null)"
case "$dm" in
cosmic-greeter.service)
	greeter_cfg="${R}/var/lib/cosmic-greeter/.config/cosmic/${BG_CONFIG}"
	if [[ -f "$greeter_cfg" ]]; then
		gsrc="$(cosmic_bg_source "$greeter_cfg")"
		if [[ "$gsrc" == /usr/share/backgrounds/tunaos/* ]]; then
			pass "cosmic-greeter background source=${gsrc}"
		else
			fail "cosmic-greeter's own background config names ${gsrc:-unparsable}, not the variant wallpaper"
		fi
	else
		pass "cosmic-greeter has no background config of its own; it draws the system default"
	fi
	;;
greetd.service)
	cmd="$(sed -n '/^\[default_session\]/,/^\[/p' "${R}/etc/greetd/config.toml" 2>/dev/null |
		sed -n 's/^[[:space:]]*command[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' | head -1)"
	# greetd's command may be a wrapper script (yellowfin:xfce runs
	# /usr/libexec/tunaos/greetd-session, which execs `cage -s -- gtkgreet -s
	# /etc/greetd/gtkgreet.css`): judge what it launches, not its name.
	launch="$cmd"
	bin="${cmd%% *}"
	if [[ -n "$bin" && -f "${R}${bin}" && "$(head -c2 "${R}${bin}" 2>/dev/null)" == '#!' ]]; then
		launch+=" $(grep -v '^[[:space:]]*#' "${R}${bin}")"
	fi
	css="$(grep -oE 'gtkgreet[^;&|]*[[:space:]]-s[[:space:]]+[^[:space:]]+' <<<"$launch" | head -1 | awk '{print $NF}')"
	css="${css:-/etc/greetd/gtkgreet.css}"
	if [[ "$launch" == *cosmic-greeter* ]]; then
		pass "greetd runs cosmic-greeter; it draws the system default"
	elif [[ "$launch" == *gtkgreet* ]]; then
		if grep -qF "$WALLPAPER" "${R}${css}" 2>/dev/null; then
			pass "gtkgreet ${css} background is ${WALLPAPER}"
		else
			fail "greetd runs gtkgreet but ${css} does not name ${WALLPAPER}"
		fi
	else
		fail "greetd runs '${cmd:-nothing}', a greeter with no TunaOS background contract"
	fi
	;;
"")
	if [[ "$mode" == --runtime ]]; then
		fail "no display-manager.service alias; no greeter to check"
	else
		echo "  note: display manager not enabled yet in this build stage; greeter checked at runtime"
	fi
	;;
*)
	fail "display manager ${dm} has no COSMIC greeter background contract"
	;;
esac

if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_BRANDING_COSMIC_FAIL variant=${variant} failures=${fails}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_COSMIC_OK variant=${variant} scope=configuration rendered=not-run" | tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
