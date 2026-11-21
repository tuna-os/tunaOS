#!/usr/bin/env bash
# Verify what GNOME Initial Setup reads, not what the image contains (#4408).
#
# 1. The accent. GDM starts Initial Setup with DCONF_PROFILE=gnome-initial-setup,
#    not the gdm or user profile. Before this check the packaged profile held no
#    system database, so the variant accent never reached the Next pill: olive
#    srgb(101,123,105) on grouper (run 42318386139), slate on bonito and
#    skipjack (run 41947529681). Read the key through that same profile.
# 2. Ubuntu's pages. Ubuntu's build adds Ubuntu Pro, "Help Improve Ubuntu", a
#    welcome page with the Ubuntu mascot, a Yaru appearance picker and an App
#    Center page (run 42374980522 showed Ubuntu Pro on grouper). When the
#    binary carries those page ids, the vendor.conf that GIS loads must skip
#    them all.
#
# This is configuration evidence, not a rendered frame. Tests prefix image
# paths with TUNAOS_BRANDING_ROOT and select the database directory with
# TUNAOS_DCONF_DB. No user settings are read or written.
set -uo pipefail

variant="${1:?usage: verify-gnome-initial-setup.sh <canonical-variant> [--runtime]}"
mode="${2:-build}"
root="${TUNAOS_BRANDING_ROOT:-}"
db_root="${TUNAOS_DCONF_DB:-${root}/etc/dconf/db}"
# The PAGE() ids of Ubuntu's own pages (gnome-initial-setup 50.0-0ubuntu7.2).
# Keep in step with UBUNTU_GIS_PAGES in build_scripts/desktop/gnome-set-branding.sh.
UBUNTU_PAGES=(welcome ubuntu_pro ubuntu_insights appearance apps)
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

gis_bin=""
for candidate in /usr/libexec/gnome-initial-setup /usr/lib/gnome-initial-setup; do
	if [[ -f "${root}${candidate}" ]]; then
		gis_bin="${root}${candidate}"
		break
	fi
done
if [[ -z "$gis_bin" ]]; then
	emit "TUNAOS_INITIAL_SETUP_OK variant=${variant} status=not-installed"
	exit 0
fi

accent="$(awk -F"'" '$1 == "TUNAOS_GNOME_ACCENT=" {print $2; exit}' \
	"${root}/usr/share/tunaos/identity.env" 2>/dev/null)"
[[ -n "$accent" ]] || fail "no TUNAOS_GNOME_ACCENT in /usr/share/tunaos/identity.env"

# Resolve the profile the way dconf does: /etc first, then the packaged one.
profile="${root}/etc/dconf/profile/gnome-initial-setup"
[[ -f "$profile" ]] || profile="${root}/usr/share/dconf/profile/gnome-initial-setup"
read_value=""
if ! command -v dconf >/dev/null 2>&1; then
	fail "dconf is required to read the Initial Setup profile"
elif [[ ! -f "$profile" ]]; then
	fail "no gnome-initial-setup dconf profile; Initial Setup reads only its packaged defaults"
elif [[ -n "$accent" ]]; then
	workspace="$(mktemp -d)" || exit 1
	mkdir -p "$workspace/home" "$workspace/config" "$workspace/cache" "$workspace/runtime"
	chmod 0700 "$workspace/runtime"
	# Rewrite system-db names to the compiled files, so a fixture root and the
	# real image both work, and a missing compile is named.
	while IFS= read -r entry || [[ -n "$entry" ]]; do
		case "$entry" in
		system-db:*)
			db="${entry#system-db:}"
			[[ -s "${db_root}/${db}" ]] || fail "profile names system-db:${db}, but ${db_root}/${db} is not compiled (run dconf update)"
			printf 'file-db:%s/%s\n' "$db_root" "$db"
			;;
		file-db:/*) printf 'file-db:%s%s\n' "$root" "${entry#file-db:}" ;;
		*) printf '%s\n' "$entry" ;;
		esac
	done <"$profile" >"$workspace/profile"
	read_value="$(HOME="$workspace/home" XDG_CONFIG_HOME="$workspace/config" \
		XDG_CACHE_HOME="$workspace/cache" XDG_RUNTIME_DIR="$workspace/runtime" \
		DCONF_PROFILE="$workspace/profile" dconf read /org/gnome/desktop/interface/accent-color)"
	if [[ "$read_value" == "'${accent}'" ]]; then
		pass "gnome-initial-setup profile reads accent-color=${read_value}"
	else
		fail "gnome-initial-setup profile reads accent-color=${read_value:-unset}, want '${accent}'; the schema default colours the Initial Setup pill"
	fi
fi

ubuntu_pages=absent
if grep -aqw ubuntu_pro "$gis_bin"; then
	# GIS loads /etc/gnome-initial-setup/vendor.conf when it exists and parses,
	# and the packaged file only otherwise (gis-driver.c).
	vendor="${root}/etc/gnome-initial-setup/vendor.conf"
	[[ -f "$vendor" ]] || vendor="${root}/usr/share/gnome-initial-setup/vendor.conf"
	skip="$(awk '/^[ \t]*\[/ {in_pages = ($0 ~ /^[ \t]*\[pages\][ \t]*$/); next}
		in_pages && /^[ \t]*skip[ \t]*=/ {sub(/^[ \t]*skip[ \t]*=[ \t]*/, ""); print; exit}' \
		"$vendor" 2>/dev/null)"
	missing=()
	for page in "${UBUNTU_PAGES[@]}"; do
		[[ ";${skip};" == *";${page};"* ]] || missing+=("$page")
	done
	if [[ "${#missing[@]}" -eq 0 ]]; then
		ubuntu_pages=skipped
		pass "Ubuntu Initial Setup pages skipped by ${vendor#"$root"}: ${skip}"
	else
		ubuntu_pages=shown
		fail "Ubuntu Initial Setup pages not skipped by ${vendor#"$root"}: ${missing[*]} (skip=${skip:-none})"
	fi
fi

if [[ "$fails" -gt 0 ]]; then
	emit "TUNAOS_INITIAL_SETUP_FAIL variant=${variant} failures=${fails}"
	exit 1
fi
emit "TUNAOS_INITIAL_SETUP_OK variant=${variant} accent=${read_value} ubuntu_pages=${ubuntu_pages}"
