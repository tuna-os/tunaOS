#!/usr/bin/env bash
# Assert that a built image actually carries TunaOS branding, rather than
# shipping the upstream base's identity with a few fields overwritten.
#
# WHY THIS EXISTS
#
# Measured on the published `grouper:gnome` (2026-08-01), every one of these
# was wrong in a *silently shipping* image:
#
#   VERSION_CODENAME="Achillobator"        <- the upstream dinosaur codename,
#                                             though 90-image-info.sh computes
#                                             "Epinephelus marginatus" and says
#                                             in a comment that it replaces it
#   SUPPORT_URL="https://help.ubuntu.com/" <- Ubuntu's, though the script sets
#                                             the TunaOS issues URL
#   LOGO=ubuntu-logo                       <- no TunaOS logo in the image at all
#   /usr/share/pixmaps: ubuntu-logo*, debian-logo*   and nothing of ours
#   /usr/share/backgrounds: Resolute_Raccoon*        i.e. stock Ubuntu
#
# HOME_URL and BUG_REPORT_URL *did* apply. So the script partially lands, which
# is the worst case: the image looks branded to a spot check and is not.
#
# The reference for what "complete" looks like is ghcr.io/ublue-os/bluefin,
# which sets ID, VARIANT, VARIANT_ID, DEFAULT_HOSTNAME, IMAGE_ID, IMAGE_VERSION
# and OSTREE_VERSION, and ships 20 entries under /usr/share/ublue-os including
# its own logo set. We ship 5.
#
# USAGE
#   verify-branding.sh <variant> [--runtime]
#
# Build mode runs against the filesystem being assembled. --runtime emits a
# ttyS0 marker for the e2e gate, in the same shape as
# verify-desktop-experience.sh, so a silent death still produces a verdict.

set -euo pipefail

variant="${1:?usage: verify-branding.sh <variant> [--runtime]}"
mode="${2:-build}"

marker_emitted=0
emit_fail_on_early_exit() {
	local rc=$?
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		echo "TUNAOS_BRANDING_FAIL variant=${variant} reason=early_exit rc=${rc}" | tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap emit_fail_on_early_exit EXIT

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

# /etc/os-release is conventionally a symlink to /usr/lib/os-release, but the
# latter is the canonical file: an image can ship it without the /etc link.
# Reading only /etc/os-release there would report *every* field as unset and
# bury the real findings under noise. TUNAOS_OS_RELEASE overrides for tests.
os_release_file=""
for candidate in "${TUNAOS_OS_RELEASE:-}" /etc/os-release /usr/lib/os-release; do
	if [[ -n "$candidate" && -r "$candidate" ]]; then
		os_release_file="$candidate"
		break
	fi
done

# Must not fail when a field is absent: an absent field is a FINDING, and
# under `set -e` a non-zero return here kills the run before it can report one.
# Measured: the first version of this script died silently at the first unset
# field (VARIANT), which is exactly the class of silent-exit bug it exists to
# catch elsewhere.
osr() {
	[[ -n "$os_release_file" ]] || return 0
	grep -E "^${1}=" "$os_release_file" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true
}

# Every base family TunaOS builds on (el10, Ubuntu, Debian, openSUSE, Gentoo,
# Arch — see scripts/resolve-flavor.sh), plus the rebuilds of each. A name we
# forget here is a name an unbranded image can ship while passing this check.
UPSTREAM_NAMES=(
	ubuntu debian fedora centos almalinux rocky rhel "red hat" redhat
	opensuse suse gentoo arch
)

# Case-insensitive substring match against the upstream denylist.
names_upstream() {
	local haystack="${1,,}" name
	for name in "${UPSTREAM_NAMES[@]}"; do
		[[ "$haystack" == *"$name"* ]] && return 0
	done
	return 1
}

# ---------------------------------------------------------------- identity --

# The fish codename is the whole point of the case statement in
# 90-image-info.sh. If VERSION_CODENAME is a dinosaur, the script's output was
# overwritten by a later step or never applied.
# Keys are QUOTED, and the hyphenated ones must stay that way. Unquoted,
# shfmt reads `[bonito-rawhide]` as an arithmetic subscript and reformats it to
# `[bonito - rawhide]` — which bash then stores as a key containing spaces, so
# the lookup for the real variant id silently misses:
#
#   FAIL: no fish codename defined for variant 'flounder-sid'
#        — add it here and in 90-image-info.sh
#
# flounder-sid:gnome, LUKS run 31093350820, with all thirteen other branding
# assertions passing. bonito-rawhide carried the identical corruption and had
# simply never been run. 90-image-info.sh was unaffected because it spells the
# same thing as a `case` pattern, which shfmt leaves alone — so the two sources
# of the codename disagreed with no diff between them to see.
declare -A FISH=(
	["yellowfin"]="Thunnus albacares" ["albacore"]="Thunnus alalunga"
	["skipjack"]="Katsuwonus pelamis" ["bonito"]="Sarda sarda"
	["bonito-rawhide"]="Sarda sarda" ["sailfin"]="Istiophorus platypterus"
	["guppy"]="Poecilia reticulata" ["grouper"]="Epinephelus marginatus"
	["marlin"]="Makaira nigricans" ["flounder"]="Platichthys flesus"
	["flounder-sid"]="Platichthys flesus" ["gurnard"]="Chelidonichthys lucerna"
	# Not a fish, and the only one: hummingbird is named for the bird, so the
	# codename is the family. 90-image-info.sh has always WRITTEN Trochilidae;
	# this table never had it to CHECK, so every hummingbird build would fail
	# the branding contract the moment one ran. All four of its declared
	# flavours are untested, which is the only reason it has not.
	["hummingbird"]="Trochilidae"
	# Wahoo (Fedora ELN): a mackerel, and the fastest bony fish in the
	# Atlantic — the lane exists to run ahead of EL11.
	["wahoo"]="Acanthocybium solandri"
)

echo "== identity =="
if [[ -z "$os_release_file" ]]; then
	fail "no readable os-release (/etc/os-release or /usr/lib/os-release) — every field below reads as unset"
else
	pass "os-release=${os_release_file}"
fi
want_codename="${FISH[$variant]:-}"
got_codename="$(osr VERSION_CODENAME)"
if [[ -z "$want_codename" ]]; then
	fail "no fish codename defined for variant '${variant}' — add it here and in 90-image-info.sh"
elif [[ "$got_codename" != "$want_codename" ]]; then
	fail "VERSION_CODENAME is '${got_codename}', want '${want_codename}' (upstream codename survived)"
else
	pass "VERSION_CODENAME=${got_codename}"
fi

got_pretty="$(osr PRETTY_NAME)"
if [[ -z "$got_pretty" ]]; then
	fail "PRETTY_NAME is unset"
elif names_upstream "$got_pretty"; then
	fail "PRETTY_NAME is '${got_pretty}' — still names the upstream distro"
else
	pass "PRETTY_NAME=${got_pretty}"
fi

# Every URL must point at us. help.ubuntu.com sends our users to a project
# that cannot help them with our image.
for field in SUPPORT_URL BUG_REPORT_URL; do
	v="$(osr "$field")"
	if [[ "$v" == *tuna-os* || "$v" == *tunaos* ]]; then
		pass "${field}=${v}"
	else
		fail "${field} is '${v}' — points away from TunaOS"
	fi
done

# bluefin sets these; we set none of them. They are what desktop UIs, bootc
# and fastfetch read to name the system.
for field in DEFAULT_HOSTNAME VARIANT VARIANT_ID IMAGE_ID IMAGE_VERSION; do
	v="$(osr "$field")"
	[[ -n "$v" ]] && pass "${field}=${v}" || fail "${field} is unset (bluefin sets it)"
done

# ------------------------------------------------------------------- logos --

echo "== logos =="
logo="$(osr LOGO)"
if [[ -z "$logo" ]]; then
	fail "LOGO is unset"
elif names_upstream "$logo"; then
	fail "LOGO=${logo} — upstream logo, not ours"
else
	pass "LOGO=${logo}"
fi

# A LOGO= naming a file that does not exist renders as a blank icon in GNOME
# About, GDM and fastfetch. Assert the referenced asset is actually present.
if [[ -n "$logo" ]]; then
	if compgen -G "/usr/share/pixmaps/${logo}.*" >/dev/null ||
		compgen -G "/usr/share/icons/hicolor/*/apps/${logo}.*" >/dev/null; then
		pass "logo asset for '${logo}' exists on disk"
	else
		fail "LOGO=${logo} but no matching file under /usr/share/pixmaps or hicolor"
	fi
fi

# ---------------------------------------------------------------- manifest --

echo "== image-info.json =="
info=/usr/share/ublue-os/image-info.json
if [[ ! -f "$info" ]]; then
	fail "missing ${info}"
else
	pass "present"
	# It must agree with os-release. Two sources of truth that disagree is how
	# an image ends up reporting one identity to bootc and another to the user.
	jname="$(python3 -c "import json;print(json.load(open('${info}')).get('image-name',''))" 2>/dev/null || echo)"
	[[ "$jname" == "$variant" ]] && pass "image-name=${jname}" ||
		fail "image-name is '${jname}', want '${variant}'"
	jvendor="$(python3 -c "import json;print(json.load(open('${info}')).get('image-vendor',''))" 2>/dev/null || echo)"
	[[ "$jvendor" == tuna-os ]] && pass "image-vendor=${jvendor}" ||
		fail "image-vendor is '${jvendor}', want 'tuna-os'"
fi

# ------------------------------------------------------------ desktop look --

echo "== desktop assets =="

# Wallpapers: shipping only the upstream set means a user sees Ubuntu's or
# Fedora's artwork on first login.
if compgen -G "/usr/share/backgrounds/tunaos*" >/dev/null ||
	compgen -G "/usr/share/backgrounds/*/tunaos*" >/dev/null ||
	compgen -G "/usr/share/backgrounds/bluefin*" >/dev/null; then
	pass "TunaOS wallpaper present"
else
	fail "no TunaOS wallpaper under /usr/share/backgrounds (only upstream artwork)"
fi

# dconf compiled database: every keyfile dir /etc/dconf/db/<name>.d/ must have
# a compiled /etc/dconf/db/<name>. Iterate instead of hardcoding local/gdm —
# distros ship their own keyfile dirs (ibus.d on Arch) already compiled by
# package postinst; hardcoding local/gdm fails those falsely.
for _dcf_dir in /etc/dconf/db/*.d; do
	[[ -d "$_dcf_dir" ]] || continue
	if compgen -G "$_dcf_dir/*" >/dev/null 2>&1; then
		_dcf_name="${_dcf_dir%.d}"
		_dcf_name="${_dcf_name##*/}"
		if [[ -s "/etc/dconf/db/${_dcf_name}" ]]; then
			pass "dconf compiled database present (${_dcf_name})"
		else
			fail "dconf keyfiles in ${_dcf_dir} but compiled database /etc/dconf/db/${_dcf_name} is missing or empty (run dconf update)"
		fi
	fi
done

# Plymouth: the boot splash is the first branded thing a user sees.
if [[ -d /usr/share/plymouth/themes/tunaos ]] ||
	[[ "$(readlink -f /usr/share/plymouth/themes/default.plymouth 2>/dev/null)" == *tunaos* ]]; then
	pass "TunaOS plymouth theme active"
else
	fail "plymouth default is not a TunaOS theme"
fi

# ublue-os asset set. bluefin ships bling, logos, motd, fastfetch config and
# more; a near-empty directory means the branding layer never ran.
echo "== ublue-os assets =="
for asset in image-info.json; do
	[[ -e "/usr/share/ublue-os/${asset}" ]] && pass "${asset}" || fail "missing /usr/share/ublue-os/${asset}"
done

# ------------------------------------------------------------------ verdict --

echo
if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_BRANDING_FAIL variant=${variant} failures=${fails}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_OK variant=${variant}" | tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
