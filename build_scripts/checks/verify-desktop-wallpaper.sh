#!/usr/bin/env bash
# Assert that COSMIC, XFCE and Pantheon, and their greeters, apply the variant
# wallpaper by default.
#
# verify-branding.sh passes when any tunaos* wallpaper file exists. These three
# desktops had no per-desktop check, so the upstream default could still be
# what a new user and the login screen saw. This check reads what each
# consumer resolves for a user who has changed nothing:
#
#   cosmic    cosmic-bg's system default RON for every config id it reads
#   xfce      xfdesktop's compiled DEFAULT_BACKDROP, system xfconf XML
#   pantheon  compiled gsettings with XDG_CURRENT_DESKTOP=Pantheon
#   greeter   the active display manager's greeter: lightdm-gtk-greeter's
#             merged config, gtkgreet's stylesheet, io.elementary.greeter's
#             fallback file, or GDM's compiled logo
#
# Each must resolve to /usr/share/backgrounds/tunaos/tunaos-default.jpg, which
# select-wallpaper.sh fills with the variant's image. The build runs it after
# <desktop>-set-branding.sh, at both install call sites. A failure stops the
# build.
#
# cosmic-greeter is the one greeter no config reaches. Before a user's first
# login it draws a background compiled into the binary (cosmic-greeter
# src/common.rs fallback_background, res/background.png). It reports
# greeter_status=open, and docs/BRANDING.md lists it as open.
#
# USAGE
#   verify-desktop-wallpaper.sh <cosmic|xfce|pantheon> [--root DIR] [--runtime]
#   verify-desktop-wallpaper.sh --xfce-default-backdrop [--root DIR]

set -euo pipefail

WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg
LETTERMARK=/usr/share/pixmaps/tunaos-lettermark.svg

desktop="${1:?usage: verify-desktop-wallpaper.sh <cosmic|xfce|pantheon> [--root DIR] [--runtime]}"
shift
root=""
mode=build
while [[ $# -gt 0 ]]; do
	case "$1" in
	--root)
		root="${2:?--root needs a directory}"
		shift 2
		;;
	--runtime)
		mode=runtime
		shift
		;;
	*)
		echo "unknown argument: $1" >&2
		exit 2
		;;
	esac
done

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

# Follow symlinks inside the image. An absolute target is relative to $root.
resolve() {
	local p="$1" t i
	for ((i = 0; i < 40; i++)); do
		[[ -L "${root}${p}" ]] || break
		t="$(readlink "${root}${p}")"
		[[ "$t" == /* ]] || t="$(dirname "$p")/${t}"
		p="$(realpath -m -s "$t")"
	done
	printf '%s\n' "$p"
}

# The image path $1 must end at the wallpaper, and the wallpaper must exist.
expect_wallpaper() {
	local what="$1" path="$2" final
	final="$(resolve "$path")"
	if [[ "$final" != "$WALLPAPER" ]]; then
		fail "${what}: ${path} resolves to ${final}, not ${WALLPAPER}"
	elif [[ ! -f "${root}${WALLPAPER}" ]]; then
		fail "${what}: ${WALLPAPER} is missing"
	else
		pass "${what}: ${path} -> ${WALLPAPER}"
	fi
}

# xfdesktop's DEFAULT_BACKDROP, read from the binary. Its /usr/share strings
# are the locale dir, its fallback icon, three legacy names it migrates
# (common/xfdesktop-common.c fixup_image_filename) and DEFAULT_BACKDROP.
# Measured identical in the EL10, Fedora, Arch, Debian 13, Debian sid and
# Ubuntu 26.04 builds. More than one candidate means xfdesktop changed: fail.
xfce_default_backdrop() {
	local bin="${root}/usr/bin/xfdesktop" candidates n
	if [[ ! -f "$bin" ]]; then
		echo "ERROR: ${bin} is missing; an XFCE image without xfdesktop draws no wallpaper." >&2
		return 1
	fi
	candidates="$(grep -a -o -E '/usr/share/[A-Za-z0-9._/+-]+' "$bin" | sort -u |
		grep -v -x -E '/usr/share/locale|/usr/share/pixmaps/xfdesktop/.*|/usr/share/backgrounds/xfce/xfce-(stripes|teal|verticals)\.png' || true)"
	n="$(grep -c . <<<"$candidates" || true)"
	if [[ "$n" -ne 1 ]]; then
		echo "ERROR: expected one DEFAULT_BACKDROP string in ${bin#"${root}"}, found ${n}:" >&2
		printf '  %s\n' $candidates >&2
		return 1
	fi
	printf '%s\n' "$candidates"
}

if [[ "$desktop" == --xfce-default-backdrop ]]; then
	xfce_default_backdrop
	exit
fi

# The display manager the image boots: the display-manager.service alias, or
# a greeter unit graphical.target wants (Fedora's greetd has no alias).
active_dm() {
	local link unit
	link="${root}/etc/systemd/system/display-manager.service"
	if [[ -L "$link" ]]; then
		unit="$(basename "$(readlink "$link")")"
		echo "${unit%.service}"
		return
	fi
	for unit in cosmic-greeter greetd lightdm gdm gdm3; do
		if [[ -L "${root}/etc/systemd/system/graphical.target.wants/${unit}.service" ]]; then
			echo "$unit"
			return
		fi
	done
	echo none
}

# lightdm's greeter-session, from the files lightdm merges, last one wins.
lightdm_greeter() {
	local f g=""
	for f in "${root}"/usr/share/lightdm/lightdm.conf.d/*.conf "${root}"/etc/lightdm/lightdm.conf.d/*.conf "${root}/etc/lightdm/lightdm.conf"; do
		[[ -f "$f" ]] || continue
		g="$(awk -F= -v g="$g" '/^[[:space:]]*\[/ { seat = ($0 ~ /^[[:space:]]*\[Seat:\*\]/ || $0 ~ /^[[:space:]]*\[SeatDefaults\]/) }
			seat && $1 ~ /^[[:space:]]*greeter-session[[:space:]]*$/ { v = $2; gsub(/[[:space:]]/, "", v); g = v }
			END { print g }' "$f")"
	done
	# Unset, lightdm uses its compiled default: lightdm-greeter (Fedora),
	# lightdm-default-greeter (openSUSE), lightdm-gtk-greeter (Arch). Debian
	# and openSUSE make those alternatives links; follow them.
	local c
	for c in ${g:-lightdm-greeter lightdm-default-greeter default lightdm-gtk-greeter}; do
		if [[ -e "${root}/usr/share/xgreeters/${c}.desktop" || -L "${root}/usr/share/xgreeters/${c}.desktop" ]]; then
			basename "$(resolve "/usr/share/xgreeters/${c}.desktop")" .desktop
			return
		fi
	done
	echo "${g:-unknown}"
}

check_lightdm_gtk_greeter() {
	local base conf bg=""
	for base in /usr/local/share /usr/share /etc/xdg /etc; do
		for conf in "${root}${base}"/lightdm/lightdm-gtk-greeter.conf.d/*.conf "${root}${base}/lightdm/lightdm-gtk-greeter.conf"; do
			[[ -f "$conf" ]] || continue
			bg="$(awk -F= -v bg="$bg" '/^[[:space:]]*\[/ { greeter = ($0 ~ /^[[:space:]]*\[greeter\]/) }
				greeter && $1 ~ /^[[:space:]]*background[[:space:]]*$/ { v = substr($0, index($0, "=") + 1); gsub(/^[[:space:]]+|[[:space:]]+$/, "", v); bg = v }
				END { print bg }' "$conf")"
		done
	done
	if [[ -z "$bg" ]]; then
		fail "lightdm-gtk-greeter: no background= in its merged config; it draws its stock colour"
	else
		expect_wallpaper "lightdm-gtk-greeter background" "$bg"
	fi
}

check_gtkgreet() {
	local css="${root}/etc/greetd/gtkgreet.css"
	if grep -qF "url(\"file://${WALLPAPER}\")" "$css" 2>/dev/null; then
		pass "gtkgreet: ${css#"${root}"} draws ${WALLPAPER}"
	else
		fail "gtkgreet: ${css#"${root}"} does not draw ${WALLPAPER}"
	fi
}

check_gdm_logo() {
	local value=""
	if [[ -z "$root" ]] && command -v dconf >/dev/null 2>&1 && [[ -f /etc/dconf/profile/gdm ]]; then
		local tmp
		tmp="$(mktemp -d)"
		value="$(XDG_CONFIG_HOME="$tmp" DCONF_PROFILE=/etc/dconf/profile/gdm dconf read /org/gnome/login-screen/logo 2>/dev/null || true)"
		rm -rf "$tmp"
	else
		value="$(sed -n 's/^logo=//p' "${root}/etc/dconf/db/gdm.d/10-tunaos-branding" 2>/dev/null || true)"
	fi
	if [[ "$value" == "'${LETTERMARK}'" ]]; then
		pass "gdm: login-screen logo ${LETTERMARK} (GDM draws no wallpaper)"
	else
		fail "gdm: login-screen logo is ${value:-unset}, not '${LETTERMARK}'"
	fi
}

# Pantheon's greeter card falls back to a fixed path when the account has no
# synced wallpaper (io.elementary.greeter 8.1.2 src/Widgets/BackgroundImage.vala).
check_elementary_greeter() {
	expect_wallpaper "io.elementary.greeter fallback" /usr/share/backgrounds/elementaryos-default
}

# gsettings as a new Pantheon user and as the greeter compositor, which sets
# XDG_CURRENT_DESKTOP=Pantheon (greeter compositor/main.vala). Per-desktop
# override sections beat plain ones in any file order.
check_pantheon_gsettings() {
	local key value
	if ! command -v gsettings >/dev/null 2>&1; then
		fail "pantheon: gsettings is missing, so the compiled default cannot be read"
		return
	fi
	local -a envs=(XDG_CURRENT_DESKTOP=Pantheon GSETTINGS_BACKEND=memory)
	if [[ -n "$root" ]]; then
		envs+=("GSETTINGS_SCHEMA_DIR=${root}/usr/share/glib-2.0/schemas" "XDG_DATA_DIRS=${root}/usr/share")
	fi
	for key in picture-uri picture-uri-dark; do
		value="$(env "${envs[@]}" gsettings get org.gnome.desktop.background "$key" 2>&1 || true)"
		if [[ "$value" == "'file://${WALLPAPER}'" ]]; then
			pass "pantheon: org.gnome.desktop.background ${key} = ${value}"
		else
			fail "pantheon: org.gnome.desktop.background ${key} = ${value}, not 'file://${WALLPAPER}'"
		fi
	done
	# A system dconf database sits above the schema default.
	local kf
	for kf in "${root}"/etc/dconf/db/*.d/*; do
		[[ -f "$kf" ]] || continue
		awk -v want="'file://${WALLPAPER}'" '/^\[/ { bg = ($0 == "[org/gnome/desktop/background]") }
			bg && /^picture-uri(-dark)?=/ { v = substr($0, index($0, "=") + 1); if (v != want) { print; bad = 1 } }
			END { exit bad }' "$kf" >/dev/null ||
			fail "pantheon: dconf keyfile ${kf#"${root}"} sets another picture-uri"
	done
}

check_greeter() {
	local dm cmd
	dm="$(active_dm)"
	case "$dm" in
	lightdm)
		greeter="$(lightdm_greeter)"
		case "$greeter" in
		lightdm-gtk-greeter) check_lightdm_gtk_greeter ;;
		io.elementary.greeter) check_elementary_greeter ;;
		*) fail "lightdm runs greeter '${greeter}', which this check does not know" ;;
		esac
		;;
	greetd)
		# The unit may name another config (cosmic-greeter.service runs
		# `greetd --config /etc/greetd/cosmic-greeter.toml`). Last ExecStart wins.
		local unit_file line config=/etc/greetd/config.toml exec=""
		for unit_file in "${root}/usr/lib/systemd/system/greetd.service" "${root}"/usr/lib/systemd/system/greetd.service.d/*.conf \
			"${root}/etc/systemd/system/greetd.service" "${root}"/etc/systemd/system/greetd.service.d/*.conf; do
			[[ -f "$unit_file" ]] || continue
			line="$(sed -n 's/^ExecStart=//p' "$unit_file" | grep . | tail -n1 || true)"
			[[ -z "$line" ]] || exec="$line"
		done
		if [[ "$exec" =~ (--config|-c)[=[:space:]]+([^[:space:]]+) ]]; then
			config="${BASH_REMATCH[2]}"
		fi
		cmd="$(sed -n 's/^[[:space:]]*command[[:space:]]*=[[:space:]]*//p' "${root}${config}" 2>/dev/null | head -n1)"
		if [[ "$cmd" == *greetd-session* || "$cmd" == *gtkgreet* ]]; then
			greeter=gtkgreet
			check_gtkgreet
		elif [[ "$cmd" == *cosmic-greeter* ]]; then
			greeter=cosmic-greeter
		else
			greeter="greetd:${cmd:-none}"
			fail "greetd runs '${cmd:-nothing}', which this check does not know"
		fi
		;;
	cosmic-greeter) greeter=cosmic-greeter ;;
	gdm | gdm3)
		greeter=gdm
		check_gdm_logo
		;;
	*)
		greeter="$dm"
		fail "no display manager found (display-manager.service alias or graphical.target.wants)"
		;;
	esac
	greeter_status=checked
	if [[ "$greeter" == cosmic-greeter ]]; then
		greeter_status=open
		echo "  open: cosmic-greeter draws its compiled-in background until the user's first login"
	fi
}

greeter=none
greeter_status=none
echo "Desktop wallpaper contract: ${desktop} (expect ${WALLPAPER})"
case "$desktop" in
cosmic)
	for id in com.system76.CosmicBackground com.system76.CosmicBackground.Dark com.system76.CosmicBackground.Light; do
		dir=""
		for data in /usr/local/share /usr/share; do
			if [[ -d "${root}${data}/cosmic/${id}/v1" ]]; then
				dir="${data}/cosmic/${id}/v1"
				break
			fi
		done
		if [[ -z "$dir" || ! -f "${root}${dir}/all" ]]; then
			fail "cosmic-bg: no system default ${id}/v1/all; cosmic-bg falls back to its stock image"
			continue
		fi
		for entry in "${root}${dir}/all" "${root}${dir}"/output.*; do
			[[ -f "$entry" ]] || continue
			src="$(grep -o 'Path("[^"]*")' "$entry" | head -n1 | sed 's/^Path("//; s/")$//')"
			expect_wallpaper "cosmic-bg ${id} ${entry##*/}" "${src:-<no Path source>}"
		done
	done
	for entry in "${root}"/etc/skel/.config/cosmic/com.system76.CosmicBackground*/v1/*; do
		[[ -f "$entry" ]] || continue
		grep -q 'Path("' "$entry" || continue
		src="$(grep -o 'Path("[^"]*")' "$entry" | head -n1 | sed 's/^Path("//; s/")$//')"
		expect_wallpaper "skeleton ${entry#"${root}"}" "$src"
	done
	check_greeter
	;;
xfce)
	if backdrop="$(xfce_default_backdrop)"; then
		expect_wallpaper "xfdesktop DEFAULT_BACKDROP" "$backdrop"
	else
		fail "xfdesktop DEFAULT_BACKDROP could not be read"
	fi
	for xml in /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml /etc/skel/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml; do
		[[ -f "${root}${xml}" ]] || continue
		while read -r img; do
			expect_wallpaper "${xml} image" "$img"
		done < <(grep -o -E 'name="(last-image|image-path|last-single-image)"[^>]*value="[^"]*"' "${root}${xml}" | sed -E 's/.*value="([^"]*)"/\1/')
	done
	check_greeter
	;;
pantheon)
	check_pantheon_gsettings
	check_greeter
	;;
*)
	echo "unknown desktop: ${desktop} (cosmic, xfce or pantheon)" >&2
	exit 2
	;;
esac

if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_DESKTOP_WALLPAPER_FAIL desktop=${desktop} greeter=${greeter} failures=${fails} mode=${mode}"
	exit 1
fi
echo "TUNAOS_DESKTOP_WALLPAPER_OK desktop=${desktop} wallpaper=${WALLPAPER} greeter=${greeter} greeter_status=${greeter_status} mode=${mode}"
