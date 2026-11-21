#!/usr/bin/env bash
# Run plain `fastfetch` the way a user does and check what it prints.
#
# projectbluefin/common aliases fastfetch to ublue-fastfetch, which runs
# Bluefin's config with --config. Only the sort order of our own alias kept the
# variant's config ahead, and that alias also used --config, so a user's
# ~/.config/fastfetch never won (measured in ghcr.io/tuna-os/bonito, main
# 69f7e8a). Aliases exist only in interactive shells, so a `bash -lc` test
# would never see them. This check starts each installed shell interactive,
# login and non-login, from a copy of /etc/skel, and asserts two things:
#
#   1. With no user config, the output names PRETTY_NAME and
#      "part of <project>", and no upstream desktop project.
#   2. With a user config, the user config wins.
#
# fastfetch finds the user config through XDG_CONFIG_HOME or the passwd home,
# not $HOME, so each probe sets XDG_CONFIG_HOME.
#
# Tests: TUNAOS_BRANDING_ROOT prefixes /etc/os-release, identity.env and
# /etc/skel; TUNAOS_FASTFETCH_SHELLS limits the shells (default bash zsh fish).
set -uo pipefail

mode="${1:-build}"
root="${TUNAOS_BRANDING_ROOT:-}"
shells="${TUNAOS_FASTFETCH_SHELLS:-bash zsh fish}"
# Word match, case-insensitive: the upstream projects whose config or logos
# ublue-fastfetch shows.
deny='(^|[^[:alnum:]])(bluefin|aurora|bazzite|universal blue|ublue)([^[:alnum:]]|$)'
fails=0
workspace=""
trap '[[ -z "$workspace" ]] || rm -rf -- "$workspace"' EXIT

fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }
emit() {
	if [[ "$mode" == --runtime ]]; then
		echo "$1" | tee /dev/ttyS0 2>/dev/null || echo "$1"
	else
		echo "$1"
	fi
}

# Some bases have no fastfetch package (noble; ELN since 2026-09). Say so.
if ! command -v fastfetch >/dev/null 2>&1; then
	emit "TUNAOS_FASTFETCH_OK status=not-installed"
	exit 0
fi
os_release="${root}/etc/os-release"
[[ -r "$os_release" ]] || os_release="${root}/usr/lib/os-release"
pretty="$(sed -n 's/^PRETTY_NAME=//p' "$os_release" 2>/dev/null | head -1 | tr -d "\"'")"
project="$(awk -F"'" '$1 == "TUNAOS_PROJECT_NAME=" {print $2; exit}' \
	"${root}/usr/share/tunaos/identity.env" 2>/dev/null)"
[[ -n "$pretty" ]] || fail "no PRETTY_NAME in ${os_release}"
[[ -n "$project" ]] || fail "no TUNAOS_PROJECT_NAME in /usr/share/tunaos/identity.env"

workspace="$(mktemp -d)" || exit 1
mkdir -p "$workspace/no-user-config" "$workspace/user-config/fastfetch"
printf '{"modules":[{"type":"custom","format":"TUNAOS_USER_CONFIG_PROBE"}]}\n' \
	>"$workspace/user-config/fastfetch/config.jsonc"

# One shell start: a fresh HOME from skel, stdin closed, stdout between markers.
run_shell() {
	local shell="$1" flags="$2" config="$3" home
	home="$(mktemp -d "$workspace/home.XXXXXX")"
	cp -a "${root}/etc/skel/." "$home/" 2>/dev/null || true
	# zsh with no rc file starts its interactive new-user wizard.
	[[ "$shell" != zsh || -e "$home/.zshrc" ]] || : >"$home/.zshrc"
	# shellcheck disable=SC2086 # flags is a list of separate options
	env -i PATH="$PATH" HOME="$home" USER="${USER:-root}" LANG=C.UTF-8 TERM=dumb \
		XDG_CONFIG_HOME="$config" \
		timeout 120 "$shell" $flags \
		'echo TUNAOS_FF_BEGIN; fastfetch --pipe -l none; echo TUNAOS_FF_END' \
		</dev/null 2>"$workspace/stderr" |
		sed -n '/^TUNAOS_FF_BEGIN$/,/^TUNAOS_FF_END$/p'
}

tested=()
system_line=""
for shell in $shells; do
	command -v "$shell" >/dev/null 2>&1 || continue
	tested+=("$shell")
	case "$shell" in
	fish) modes=("--login --interactive -c" "--interactive -c") ;;
	*) modes=("-lic" "-ic") ;;
	esac
	for flags in "${modes[@]}"; do
		label="${shell} ${flags% -c}"
		out="$(run_shell "$shell" "$flags" "$workspace/no-user-config")"
		if [[ -z "$out" ]]; then
			fail "${label}: no fastfetch output; stderr: $(tail -3 "$workspace/stderr" | tr '\n' ' ')"
			continue
		fi
		line="$(grep -F "part of ${project}" <<<"$out" | head -1)"
		if [[ -z "$line" ]]; then
			fail "${label}: output lacks \"part of ${project}\": $(head -5 <<<"$out" | tr '\n' '|')"
		elif [[ "$line" != *"$pretty"* ]]; then
			fail "${label}: system line lacks PRETTY_NAME '${pretty}': ${line}"
		else
			system_line="$line"
		fi
		if denied="$(grep -Eio "$deny" <<<"$out" | head -1)" && [[ -n "$denied" ]]; then
			fail "${label}: output names an upstream project (${denied//[^[:alnum:] ]/})"
		fi
		out="$(run_shell "$shell" "$flags" "$workspace/user-config")"
		if ! grep -q TUNAOS_USER_CONFIG_PROBE <<<"$out" || grep -qF "part of ${project}" <<<"$out"; then
			fail "${label}: a user's ~/.config/fastfetch does not win: $(head -3 <<<"$out" | tr '\n' '|')"
		fi
	done
done
[[ "${#tested[@]}" -gt 0 ]] || fail "none of the shells '${shells}' is installed"

shell_list="$(
	IFS=,
	echo "${tested[*]}"
)"
if [[ "$fails" -gt 0 ]]; then
	emit "TUNAOS_FASTFETCH_FAIL failures=${fails} shells=${shell_list}"
	exit 1
fi
pass "user config wins in every shell"
emit "TUNAOS_FASTFETCH_OK shells=${shell_list} system=\"$(printf '%s' "$system_line" | tr -s '[:space:]' ' ')\""
