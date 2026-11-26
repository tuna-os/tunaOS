#!/usr/bin/env bash
# XFCE branding contract: the wallpaper the session applies and the login
# screen draws.
#
# WHAT XFCE READS
#
#   session   xfdesktop keys its wallpaper on the monitor's connector name
#             (/backdrop/screen0/monitor<eDP-1>/workspace0/last-image), which
#             no build-time file can know. A monitor with no such key draws
#             DEFAULT_BACKDROP, a path compiled into xfdesktop, and
#             xfce-set-branding.sh links that path to the wallpaper
#             (docs/BRANDING.md). So the contract is that link, plus the
#             per-account readback in verify-branding-runtime.sh
#             (desktop.xfce.user), which reads the xfconf channel file
#             xfconfd persists: xfconf-query itself needs the session's bus.
#   greeter   LightDM's GTK greeter merges
#             /usr/share/lightdm/lightdm-gtk-greeter.conf.d/*.conf,
#             /etc/lightdm/lightdm-gtk-greeter.conf.d/*.conf and
#             /etc/lightdm/lightdm-gtk-greeter.conf, last one wins; greetd
#             with gtkgreet reads /etc/greetd/gtkgreet.css (greetd-gtkgreet.sh).
#
# Configuration evidence only; it does not prove pixels.
#
# USAGE
#   verify-branding-xfce.sh <canonical-variant> [--runtime]
# TUNAOS_BRANDING_ROOT prefixes every image path for tests.

set -uo pipefail

variant="${1:?usage: verify-branding-xfce.sh <canonical-variant> [--runtime]}"
mode="${2:-build}"
R="${TUNAOS_BRANDING_ROOT:-}"
fails=0
marker_emitted=0
finish() {
	local rc=$?
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		echo "TUNAOS_BRANDING_XFCE_FAIL variant=${variant} reason=early_exit rc=${rc}" | tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap finish EXIT
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg

canonical=""
for candidate in "${variant}-xfce.jpg" "${variant}.jpg"; do
	if [[ -f "${R}/usr/share/backgrounds/tunaos/${candidate}" ]]; then
		canonical="/usr/share/backgrounds/tunaos/${candidate}"
		break
	fi
done
echo "== xfce wallpaper =="
if [[ -z "$canonical" ]]; then
	fail "no canonical wallpaper for variant=${variant} (${variant}-xfce.jpg or ${variant}.jpg)"
elif ! cmp -s "${R}${WALLPAPER}" "${R}${canonical}"; then
	fail "${WALLPAPER} is not the bytes of ${canonical}"
else
	pass "${WALLPAPER} = ${canonical}"
fi

# No first-login applier: xfce-set-branding.sh dropped it (on Wayland it saw
# no monitor) and links xfdesktop's compiled DEFAULT_BACKDROP instead. With no
# last-image key xfdesktop draws that default:
# /usr/share/backgrounds/xfce/xfce-x.svg in yellowfin:xfce's xfdesktop. The
# other paths in the binary are the alternatives its settings dialog offers.
xfdesktop_bin=""
for candidate in "${R}/usr/bin/xfdesktop" "${R}/usr/local/bin/xfdesktop"; do
	[[ -f "$candidate" ]] && xfdesktop_bin="$candidate" && break
done
if [[ -z "$xfdesktop_bin" ]]; then
	echo "  note: xfdesktop is not installed; no compiled default backdrop to check"
else
	defaults="$(grep -a -o -E '/usr/share/backgrounds/[A-Za-z0-9._/+-]+' "$xfdesktop_bin" | sort -u |
		grep -vxE '/usr/share/backgrounds/xfce/xfce-(stripes|teal|verticals)\.png' || true)"
	if [[ -z "$defaults" ]]; then
		echo "  note: no compiled default backdrop path found in ${xfdesktop_bin#"$R"}"
	fi
	while IFS= read -r backdrop; do
		[[ -n "$backdrop" ]] || continue
		if [[ -e "${R}${backdrop}" ]] && cmp -s "${R}${backdrop}" "${R}${WALLPAPER}"; then
			pass "xfdesktop's compiled default ${backdrop} is the variant wallpaper"
		else
			fail "xfdesktop's compiled default ${backdrop} is not the variant wallpaper: an account without last-image sees it"
		fi
	done <<<"$defaults"
fi

echo "== xfce greeter =="
# The value LightDM's GTK greeter ends up with: files in its own load order,
# the last `background=` in the [greeter] group of the last file wins.
gtk_greeter_background() {
	local f value=""
	for f in "${R}"/usr/share/lightdm/lightdm-gtk-greeter.conf.d/*.conf \
		"${R}"/etc/lightdm/lightdm-gtk-greeter.conf.d/*.conf \
		"${R}/etc/lightdm/lightdm-gtk-greeter.conf"; do
		[[ -f "$f" ]] || continue
		local v
		v="$(awk '/^\[/ { g = ($0 == "[greeter]") } g && /^[[:space:]]*background[[:space:]]*=/ { sub(/^[^=]*=[[:space:]]*/, ""); print }' "$f" | tail -1)"
		[[ -z "$v" ]] || value="$v"
	done
	printf '%s' "$value"
}
lightdm_greeter_session() {
	local f value=""
	for f in "${R}"/usr/share/lightdm/lightdm.conf.d/*.conf "${R}"/etc/lightdm/lightdm.conf.d/*.conf "${R}/etc/lightdm/lightdm.conf"; do
		[[ -f "$f" ]] || continue
		local v
		v="$(sed -n 's/^[[:space:]]*greeter-session[[:space:]]*=[[:space:]]*//p' "$f" | tail -1)"
		[[ -z "$v" ]] || value="$v"
	done
	printf '%s' "$value"
}

dm="$(basename "$(readlink "${R}/etc/systemd/system/display-manager.service" 2>/dev/null)" 2>/dev/null)"
case "$dm" in
lightdm.service)
	session="$(lightdm_greeter_session)"
	case "${session:-lightdm-gtk-greeter}" in
	lightdm-gtk-greeter)
		bg="$(gtk_greeter_background)"
		if [[ "$bg" == "$WALLPAPER" ]]; then
			pass "lightdm-gtk-greeter background=${bg}"
		else
			fail "lightdm-gtk-greeter background=${bg:-unset (greeter default)}, want ${WALLPAPER}"
		fi
		;;
	*)
		fail "LightDM greeter-session=${session} has no TunaOS background contract"
		;;
	esac
	;;
gdm.service)
	# bonito:xfce logs in through GDM: its login-screen logo is the branded surface.
	logo=""
	if command -v dconf >/dev/null 2>&1 && [[ -f "${R}/etc/dconf/profile/gdm" ]]; then
		logo="$(DCONF_PROFILE="${R}/etc/dconf/profile/gdm" dconf read /org/gnome/login-screen/logo 2>/dev/null || true)"
	fi
	if [[ "$logo" == "'/usr/share/pixmaps/tunaos-lettermark.svg'" ]]; then
		pass "GDM login-screen logo=${logo}"
	else
		fail "GDM login-screen logo=${logo:-unset}, want '/usr/share/pixmaps/tunaos-lettermark.svg'"
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
	if [[ "$launch" == *gtkgreet* ]] && grep -qF "$WALLPAPER" "${R}${css}" 2>/dev/null; then
		pass "greetd runs gtkgreet; ${css} background is ${WALLPAPER}"
	else
		fail "greetd runs '${cmd:-nothing}' without a gtkgreet stylesheet (${css}) naming ${WALLPAPER}"
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
	fail "display manager ${dm} has no XFCE greeter background contract"
	;;
esac

if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_BRANDING_XFCE_FAIL variant=${variant} failures=${fails}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_XFCE_OK variant=${variant} scope=configuration rendered=not-run" | tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
