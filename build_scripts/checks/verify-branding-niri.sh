#!/usr/bin/env bash
# niri branding contract.
#
# WHY NIRI IS DIFFERENT
#
# niri has no desktop-environment theming layer — no look-and-feel package, no
# settings daemon, no wallpaper service of its own. Its branded surfaces are
# exactly three: the greeter, the compositor's default config, and whatever
# draws the background. Each is a plain file, and each is silently optional,
# which is why they need asserting rather than eyeballing.
#
# MEASURED on yellowfin:niri (2026-08-01):
#
#   /etc/greetd/config.toml     present, and it launches:
#       dms-greeter --command niri -C /etc/greetd/niri/config.kdl
#   /etc/greetd/niri/config.kdl  DOES NOT EXIST      <- greeter told to load a
#                                                        config file that is
#                                                        absent
#   /etc/niri/  /usr/share/niri/  DO NOT EXIST       <- no default compositor
#                                                        config ships at all
#   config.kdl anywhere on the image                 <- none found
#   swaybg / swww / wpaperd                          <- none installed
#
# So: the greeter is pointed at a missing file, no default niri config is
# shipped, and nothing capable of drawing a wallpaper is installed. A first
# boot gets whatever niri's built-in defaults are, on a blank background.
#
# The greeter itself IS branded — /usr/share/quickshell/dms-greeter/ ships
# DMSGreeter.qml and a CODENAME file — so this is a case of one surface being
# done and the other two missing, the same partial-application pattern as
# os-release.
#
# WHICH greeter that is, though, is per-base and must not be hardcoded:
#
#   fedora / el10        dms-greeter          (avengemedia/dms-git COPR)
#   opensuse / arch      gtkgreet under cage  (greetd-gtkgreet.sh)
#
# so the greeter assertion below is on whatever greetd is configured to exec,
# not on one variant's shell. See the comment at that check for why the stock
# `agreety` config is a restart loop rather than a fallback.
#
# USAGE
#   verify-branding-niri.sh <variant> [--runtime]

set -euo pipefail

variant="${1:?usage: verify-branding-niri.sh <variant> [--runtime]}"
mode="${2:-build}"

marker_emitted=0
trap 'rc=$?; if [[ "$mode" == --runtime && $rc -ne 0 && $marker_emitted -eq 0 ]]; then
	echo "TUNAOS_BRANDING_NIRI_FAIL variant=${variant} reason=early_exit rc=${rc}" | tee /dev/ttyS0 2>/dev/null || true
fi' EXIT

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

echo "== greeter =="
# TUNAOS_GREETD_CONFIG overrides for tests, as TUNAOS_OS_RELEASE does in
# verify-branding.sh.
GREETD="${TUNAOS_GREETD_CONFIG:-/etc/greetd/config.toml}"
if [[ ! -f "$GREETD" ]]; then
	fail "missing ${GREETD} — no greeter configured"
else
	pass "greetd config present"
	# Keep the raw value: the binary greetd execs is argv[0] of this string, so
	# stripping spaces (as this did) makes it impossible to recover.
	raw="$(grep -E '^[[:space:]]*command[[:space:]]*=' "$GREETD" 2>/dev/null | head -1 |
		cut -d= -f2- | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' || true)"
	[[ -n "$raw" ]] && pass "default_session command set" || fail "no default_session command"

	# The -C argument names a config the greeter loads at startup. greetd does
	# not fail loudly when it is missing; the greeter just comes up bare.
	refc="$(grep -oE '\-C +[^" ]+' "$GREETD" 2>/dev/null | head -1 | awk '{print $2}' || true)"
	if [[ -n "$refc" ]]; then
		if [[ -f "$refc" ]]; then
			pass "greeter config ${refc} exists"
		else
			fail "greetd references ${refc} with -C, but that file DOES NOT EXIST"
		fi
	fi

	# THE GREETER GREETD ACTUALLY LAUNCHES MUST BE ON THE IMAGE.
	#
	# This used to assert /usr/share/quickshell/dms-greeter/DMSGreeter.qml
	# unconditionally, which only described the Fedora/EL10 variants. There are
	# three greeters in the tree: dms-greeter (COPR), gtkgreet under cage
	# (build_scripts/desktop/greetd-gtkgreet.sh) and cosmic-greeter, so a
	# hardcoded path reddens every variant that correctly uses a different one.
	# marlin:niri died here on a DMS file it was never meant to have.
	#
	# Checking argv[0] instead covers all three, and catches the sharper bug:
	# greetd's stock config names `agreety`, which on Arch ships in a SEPARATE
	# package (greetd-agreety) that no manifest installed. A config naming an
	# absent binary is not a text prompt, it is greetd exiting and being
	# restarted forever by Restart=always: a black screen with nothing on the
	# console, the same failure greetd-gtkgreet.sh documents at length.
	argv0="${raw%% *}"
	if [[ -z "$argv0" ]]; then
		: # already reported as "no default_session command"
	elif [[ "$argv0" == /* ]]; then
		if [[ -x "$argv0" ]]; then
			pass "greeter command ${argv0} present"
		else
			fail "greetd launches ${argv0}, which is not executable on this image"
		fi
	elif command -v "$argv0" >/dev/null 2>&1; then
		pass "greeter command ${argv0} present"
	else
		fail "greetd launches '${argv0}', which is NOT installed; greetd will restart-loop, not fall back"
	fi

	# agreety is greetd's bundled agetty-lookalike: a text prompt into a bare
	# shell, no session picker and nothing branded. Reaching a login that way
	# means the graphical greeter was never wired up.
	if [[ "${argv0##*/}" == agreety ]]; then
		fail "greetd is still on its stock agreety text prompt; no graphical greeter configured"
	fi

	# The DMS shell, asserted only where greetd is configured to launch it.
	if [[ "$raw" == *dms-greeter* ]]; then
		if [[ -f /usr/share/quickshell/dms-greeter/DMSGreeter.qml ]]; then
			pass "dms-greeter shell present"
		else
			fail "greetd launches dms-greeter but /usr/share/quickshell/dms-greeter/DMSGreeter.qml is missing"
		fi
	fi
fi

echo "== compositor defaults =="
# Without a shipped default, a first-boot user gets niri's upstream built-in
# config: no keybind hints, no branded look, nothing we chose.
if [[ -f /etc/niri/config.kdl ]] || [[ -f /usr/share/niri/config.kdl ]] ||
	compgen -G "/etc/skel/.config/niri/config.kdl" >/dev/null; then
	pass "default niri config ships"
else
	fail "no default niri config in /etc/niri, /usr/share/niri or /etc/skel — first boot gets upstream defaults"
fi

echo "== session registration =="
if [[ -f /usr/share/wayland-sessions/niri.desktop ]]; then
	pass "niri.desktop session file present"
	n="$(grep -E '^Name=' /usr/share/wayland-sessions/niri.desktop 2>/dev/null | head -1 | cut -d= -f2- || true)"
	[[ -n "$n" ]] && pass "session Name=${n}" || fail "niri.desktop has no Name="
else
	fail "missing /usr/share/wayland-sessions/niri.desktop"
fi

echo "== background =="
# niri draws no wallpaper itself. If nothing here can, the desktop is a solid
# colour no matter what artwork the image ships.
found_bg=""
for b in swaybg swww wpaperd hyprpaper; do
	command -v "$b" >/dev/null 2>&1 && found_bg="$b"
done
if [[ -n "$found_bg" ]]; then
	pass "wallpaper daemon available: ${found_bg}"
else
	# dms/quickshell can draw its own background, so this is a warning-level
	# finding only when dms is also absent.
	if [[ -d /usr/share/quickshell/dms-greeter ]]; then
		pass "no wallpaper daemon, but dms/quickshell can draw the background"
	else
		fail "no wallpaper daemon (swaybg/swww/wpaperd) and no dms — background will be blank"
	fi
fi

if compgen -G "/usr/share/backgrounds/tunaos*" >/dev/null ||
	compgen -G "/usr/share/backgrounds/*/tunaos*" >/dev/null; then
	pass "TunaOS wallpaper asset present"
else
	fail "no TunaOS wallpaper asset under /usr/share/backgrounds"
fi

echo
if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_BRANDING_NIRI_FAIL variant=${variant} failures=${fails}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_NIRI_OK variant=${variant}" | tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
