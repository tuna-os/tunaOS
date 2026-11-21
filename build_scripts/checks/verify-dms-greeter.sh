#!/usr/bin/env bash
# DMS greeter branding contract: the greeter greetd launches resolves its
# wallpaper and its fallback mark to the variant's files.
#
# It reads what the greeter reads, in the greeter's order:
#   1. greetd's default_session command: dms-greeter, its --cache-dir
#      (default /var/cache/dms-greeter) and its -p shell path.
#   2. <cache dir>/session.json, key wallpaperPath (both DMS 1.6 and
#      dms-greeter 2.x). At build time /var is empty, so the file comes from
#      tmpfiles.d: the first file by name, /etc before /run before /usr, with
#      a line for that path wins, as in systemd-tmpfiles. At --runtime the
#      file itself is read.
#   3. <cache dir>/settings.json, if present: greeterWallpaperPath (1.6) and
#      lockScreenWallpaperPath (2.x) override session.json.
#   4. <shell dir>/assets/danklogonormal.svg, which DankBackdrop draws when
#      no wallpaper loads. It must be the variant mark, not DMS's mascot.
#
# A greetd that does not launch dms-greeter (gtkgreet on Arch and openSUSE)
# is not applicable and passes.
#
# USAGE
#   verify-dms-greeter.sh <variant> [--runtime] [--root DIR]
#
# Output, one line:
#   TUNAOS_DMS_GREETER_OK variant=<v> wallpaper=<path> logo=<path> session=<source> mode=<build|runtime>
#   TUNAOS_DMS_GREETER_SKIP variant=<v> reason=greeter-not-dms greeter=<argv0> mode=<mode>
#   TUNAOS_DMS_GREETER_FAIL variant=<v> failures=<n> mode=<mode>

set -euo pipefail

WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg
LOGO=/usr/share/pixmaps/tunaos.svg

variant=""
mode=build
root=""
while [[ $# -gt 0 ]]; do
	case "$1" in
	--runtime) mode=runtime ;;
	--root)
		root="${2:?--root needs a directory}"
		shift
		;;
	*) variant="$1" ;;
	esac
	shift
done
: "${variant:?usage: verify-dms-greeter.sh <variant> [--runtime] [--root DIR]}"

marker() {
	if [[ "$mode" == runtime ]]; then
		echo "$1" | tee /dev/ttyS0 2>/dev/null || echo "$1"
	else
		echo "$1"
	fi
}

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

# The string value of a top-level key in a flat JSON file; empty when absent.
json_string() {
	sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$2" | head -1
}
json_true() {
	grep -qE "\"$1\"[[:space:]]*:[[:space:]]*true" "$2"
}

# Where systemd-tmpfiles at first boot gets <path> from: prints "<type> <arg>".
tmpfiles_entry() {
	local want="$1" dir f name type path _mode _user _group _age arg
	local -A seen=()
	local -a files=()
	for dir in /etc/tmpfiles.d /run/tmpfiles.d /usr/local/lib/tmpfiles.d /usr/lib/tmpfiles.d; do
		for f in "${root}${dir}"/*.conf; do
			[[ -f "$f" ]] || continue
			name="${f##*/}"
			[[ -n "${seen[$name]:-}" ]] && continue
			seen[$name]=1
			files+=("$name"$'\t'"$f")
		done
	done
	[[ ${#files[@]} -gt 0 ]] || return 1
	while IFS=$'\t' read -r _ f; do
		while read -r type path _mode _user _group _age arg; do
			[[ -z "$type" || "$type" == \#* ]] && continue
			if [[ "$path" == "$want" ]]; then
				echo "${type} ${arg}"
				return 0
			fi
		done <"$f"
	done < <(printf '%s\n' "${files[@]}" | LC_ALL=C sort -t$'\t' -k1,1)
	return 1
}

# The file the greeter will open for <cache>/<name>, as a path under $root.
# Prints "<file>|<source>"; nothing when nothing creates it. A non-blank
# separator, because read collapses a leading empty field split on a tab.
greeter_file() {
	local want="$1" entry type arg
	if [[ "$mode" == runtime ]]; then
		if [[ -L "${root}${want}" || -e "${root}${want}" ]]; then
			printf '%s|%s\n' "${root}${want}" "file:${want}=>$(readlink -m "${root}${want}")"
		fi
		return 0
	fi
	entry="$(tmpfiles_entry "$want")" || return 0
	type="${entry%% *}"
	arg="${entry#* }"
	case "$type" in
	L | L+ | C | C+)
		[[ -z "$arg" || "$arg" == - ]] && arg="/usr/share/factory${want}"
		printf '%s|%s\n' "${root}${arg}" "tmpfiles:${type}:${arg}"
		;;
	*) printf '%s|%s\n' "" "tmpfiles:${type}:not-a-copy-or-link" ;;
	esac
}

echo "== DMS greeter =="
greetd="${TUNAOS_GREETD_CONFIG:-${root}/etc/greetd/config.toml}"
command_line="$(sed -n '/^\[default_session\]/,/^\[/{s/^[[:space:]]*command[[:space:]]*=[[:space:]]*"\(.*\)"[[:space:]]*$/\1/p}' "$greetd" 2>/dev/null | head -1 || true)"
if [[ "$command_line" != *dms-greeter* ]]; then
	argv0="${command_line%% *}"
	marker "TUNAOS_DMS_GREETER_SKIP variant=${variant} reason=greeter-not-dms greeter=${argv0:-none} mode=${mode}"
	exit 0
fi
pass "greetd launches: ${command_line}"

cache_dir=/var/cache/dms-greeter
shell_path=dms-greeter
read -ra argv <<<"$command_line"
for ((i = 0; i < ${#argv[@]} - 1; i++)); do
	case "${argv[i]}" in
	--cache-dir) cache_dir="${argv[i + 1]}" ;;
	-p | --path) shell_path="${argv[i + 1]}" ;;
	esac
done

# ── wallpaper ───────────────────────────────────────────────────────────────
wallpaper=""
session_src=""
IFS='|' read -r session_file session_src < <(greeter_file "${cache_dir}/session.json") || true
if [[ -z "${session_src:-}" ]]; then
	fail "nothing creates ${cache_dir}/session.json; the greeter draws DankBackdrop and the DMS mascot"
elif [[ -z "$session_file" || ! -f "$session_file" ]]; then
	fail "${cache_dir}/session.json comes from ${session_src}, which does not exist; the greeter draws the DMS mascot"
else
	wallpaper="$(json_string wallpaperPath "$session_file")"
	if json_true perMonitorWallpaper "$session_file"; then
		fail "${cache_dir}/session.json sets perMonitorWallpaper; the wallpaper depends on the connector"
	fi
	if [[ "$wallpaper" == "$WALLPAPER" ]]; then
		pass "${cache_dir}/session.json (${session_src}) wallpaperPath=${wallpaper}"
	else
		fail "${cache_dir}/session.json (${session_src}) wallpaperPath='${wallpaper}', expected ${WALLPAPER}"
	fi
fi

IFS='|' read -r settings_file _ < <(greeter_file "${cache_dir}/settings.json") || true
if [[ -n "${settings_file:-}" && -f "$settings_file" ]]; then
	for key in greeterWallpaperPath lockScreenWallpaperPath; do
		value="$(json_string "$key" "$settings_file")"
		if [[ -n "$value" && "$value" != "$WALLPAPER" ]]; then
			fail "${cache_dir}/settings.json ${key}='${value}' overrides the session wallpaper"
		fi
	done
fi

if [[ -f "${root}${WALLPAPER}" ]]; then
	pass "${WALLPAPER} present"
else
	fail "${WALLPAPER} is missing"
fi

# ── fallback mark ───────────────────────────────────────────────────────────
# The launcher's search order (dms-greeter locate_dms_config, HOME=cache dir).
shell_dir=""
if [[ "$shell_path" == /* ]]; then
	shell_dir="$shell_path"
else
	for d in "${cache_dir}/.config/quickshell/${shell_path}" "/usr/share/quickshell/${shell_path}" "/etc/xdg/quickshell/${shell_path}"; do
		if [[ -f "${root}${d}/shell.qml" ]]; then
			shell_dir="$d"
			break
		fi
	done
fi

logo="embedded"
if [[ -z "$shell_dir" ]]; then
	# dms-greeter 2.x embeds its UI; it draws the mark only without a wallpaper.
	pass "no greeter QML tree on disk; the mark is embedded and shows only without a wallpaper"
else
	asset="${root}${shell_dir}/assets/danklogonormal.svg"
	if [[ -L "$asset" && "$(readlink "$asset")" == "$LOGO" && -f "${root}${LOGO}" ]]; then
		logo="$LOGO"
		pass "${shell_dir}/assets/danklogonormal.svg -> ${LOGO}"
	elif [[ -f "$asset" && -f "${root}${LOGO}" ]] && cmp -s "$asset" "${root}${LOGO}"; then
		logo="$LOGO"
		pass "${shell_dir}/assets/danklogonormal.svg matches ${LOGO}"
	else
		fail "${shell_dir}/assets/danklogonormal.svg is not ${LOGO}; the fallback backdrop shows the DMS mascot"
	fi
fi

echo
if [[ "$fails" -gt 0 ]]; then
	marker "TUNAOS_DMS_GREETER_FAIL variant=${variant} failures=${fails} mode=${mode}"
	exit 1
fi
marker "TUNAOS_DMS_GREETER_OK variant=${variant} wallpaper=${wallpaper} logo=${logo} session=${session_src} mode=${mode}"
