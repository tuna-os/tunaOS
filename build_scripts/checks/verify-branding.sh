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
#   verify-branding.sh <variant>                 build mode
#   verify-branding.sh [<variant>] --runtime     on the booted system
#
# Build mode runs against the filesystem being assembled and checks layers 1
# and 2 (docs/BRANDING.md). --runtime is the ONE checker the booted system
# runs (tunaos-branding-contract.service): the same layer 1/2 checks against
# the running root, the runtime assertions in verify-branding-runtime.sh
# (os-release, hostname, boot entries, firmware labels, initramfs splash,
# flatpak remotes, fastfetch, /etc/issue, each account's applied look) and the
# per-desktop checker. It prints, on the serial console,
#
#   TUNAOS_BRANDING_REPORT {"schema":1,...,"checks":[{"id":..,"status":..,"detail":..}]}
#   TUNAOS_BRANDING_OK variant=<v> desktop=<d> checks=<n> skipped=<k>
#   TUNAOS_BRANDING_FAIL variant=<v> desktop=<d> failed=<id,id,...>
#
# and exits non-zero on FAIL, so the unit fails. The verdict line alone is
# sufficient: consumers (scripts/corral-boot-gate.sh, the strict harness) take
# the JSON as evidence, the verdict as the result. With no <variant>, runtime
# reads the publish name from /usr/share/ublue-os/image-info.json.

set -euo pipefail

if [[ "${1:-}" == --runtime ]]; then
	mode=--runtime
	variant="$(sed -n 's/^[[:space:]]*"image-name":[[:space:]]*"\([^"]*\)".*/\1/p' \
		"${TUNAOS_BRANDING_ROOT:-}/usr/share/ublue-os/image-info.json" 2>/dev/null | head -1)"
	variant="${variant:-unknown}"
else
	variant="${1:?usage: verify-branding.sh <variant> | verify-branding.sh [<variant>] --runtime}"
	mode="${2:-build}"
fi

# The desktop whose checker runs: the unit's environment (written by the
# desktop stage), else the flavor 90-image-info.sh recorded (gnome-hwe ->
# gnome). Runtime only.
desktop="${TUNAOS_BRANDING_DESKTOP:-}"
if [[ -z "$desktop" && "$mode" == --runtime ]]; then
	desktop="$(sed -n 's/^[[:space:]]*"image-flavor":[[:space:]]*"\([^"]*\)".*/\1/p' \
		"${TUNAOS_BRANDING_ROOT:-}/usr/share/ublue-os/image-info.json" 2>/dev/null | head -1)"
	desktop="${desktop%%-*}"
fi
desktop="${desktop:-base}"

marker_emitted=0
emit_fail_on_early_exit() {
	local rc=$?
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		echo "TUNAOS_BRANDING_FAIL variant=${variant} desktop=${desktop} failed=early_exit rc=${rc}" | tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap emit_fail_on_early_exit EXIT

fails=0
fail_messages=()
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
	fail_messages+=("$*")
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

# The codename 90-image-info.sh wrote must survive to the finished image. If
# VERSION_CODENAME is a dinosaur, a later step overwrote it or it never ran.
# Expected values come from the same generated adapter the writer used, so a
# fork's own codenames pass and there is no second table to drift out of step
# (two copies once disagreed for flounder-sid, LUKS run 31093350820). Build mode
# reads the generated build-context adapter; 90-image-info.sh installs that same
# adapter at /usr/share/tunaos/identity-config.env for the runtime checker.
identity_env=""
local_identity="$(dirname "${BASH_SOURCE[0]}")/../lib/identity.env"
identity_override=""
if [[ -f "$local_identity" && -n "${TUNAOS_IDENTITY_ENV:-}" && "${TUNAOS_IDENTITY_TEST_OVERRIDE:-}" != 1 ]]; then
	echo "ERROR: TUNAOS_IDENTITY_ENV is test-only; branding verification must use ${local_identity}" >&2
	exit 1
fi
# Only the source-tree checker accepts an override. The installed verifier must
# read the root-owned adapter shipped in the image, never a caller-controlled path.
if [[ -f "$local_identity" ]]; then
	identity_override="${TUNAOS_IDENTITY_ENV:-}"
fi
for candidate in "$identity_override" "$local_identity" /usr/share/tunaos/identity-config.env; do
	if [[ -n "$candidate" && -f "$candidate" && -r "$candidate" ]]; then
		identity_env="$candidate"
		break
	fi
done
declare -A TUNAOS_CODENAMES=()
identity_source_failed=false
if [[ -n "$identity_env" ]]; then
	# shellcheck source=../lib/identity.env
	if ! source "$identity_env"; then
		fail "identity adapter could not be sourced: ${identity_env}"
		identity_source_failed=true
	fi
fi

echo "== identity =="
if [[ -z "$os_release_file" ]]; then
	fail "no readable os-release (/etc/os-release or /usr/lib/os-release) — every field below reads as unset"
else
	pass "os-release=${os_release_file}"
fi
want_codename="${TUNAOS_CODENAMES[$variant]:-}"
got_codename="$(osr VERSION_CODENAME)"
if [[ -z "$identity_env" ]]; then
	fail "no identity adapter readable (build_scripts/lib/identity.env or /usr/share/tunaos/identity-config.env)"
elif [[ "$identity_source_failed" == true ]]; then
	: # The source failure above is the authoritative adapter diagnostic.
elif [[ -z "$want_codename" ]]; then
	fail "no codename defined in tunaos.toml for variant '${variant}'"
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

# Every URL must point at the project. help.ubuntu.com sends our users to a
# project that cannot help them with our image.
#
# All four, not two. This loop read SUPPORT_URL and BUG_REPORT_URL alone, and
# the two it skipped were wrong on every single variant — HOME_URL and
# DOCUMENTATION_URL named projectbluefin.io, inherited from the upstream script
# (docs/BRANDING.md). A field no check reads is a field nobody notices.
#
# Each field is compared with the value generated from tunaos.toml that
# 90-image-info.sh wrote. A substring test for tuna-os/tunaos failed every fork
# that names its own project, and passed any URL that merely contained it.
for field in HOME_URL DOCUMENTATION_URL SUPPORT_URL BUG_REPORT_URL; do
	want_var=""
	v="$(osr "$field")"
	case "$field" in
	HOME_URL) want_var=TUNAOS_HOME_URL ;;
	DOCUMENTATION_URL) want_var=TUNAOS_DOCUMENTATION_URL ;;
	SUPPORT_URL) want_var=TUNAOS_SUPPORT_URL ;;
	BUG_REPORT_URL) want_var=TUNAOS_BUG_REPORT_URL ;;
	*)
		fail "unsupported identity URL field: ${field}"
		continue
		;;
	esac
	want_url="${!want_var:-}"
	if [[ -z "$want_url" ]]; then
		fail "${field}: no expected URL (${want_var} is unset; identity adapter unreadable)"
	elif [[ "$v" == "$want_url" ]]; then
		pass "${field}=${v}"
	else
		fail "${field} is '${v}', want '${want_url}'"
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

# ---------------------------------------------------------- identity tokens --

# system_files writes @TUNAOS_<NAME>@ where a file names the project, and
# 90-image-info.sh fills them from the identity adapter. A token that survives
# means that script ran before the file was copied (or not at all), and the
# image would show "@TUNAOS_PROJECT_NAME@" in KDE settings or systemctl.
echo "== identity tokens =="
leftover=""
for tokenized in /usr/share/plasma/look-and-feel/org.tunaos.desktop/metadata.json \
	/usr/share/plasma/look-and-feel/org.tunaos.light.desktop/metadata.json \
	/usr/share/wallpapers/TunaOS/metadata.json \
	/usr/lib/systemd/system/tunaos-live-ready.service \
	/usr/lib/systemd/system/tunaos-countme.service \
	/usr/lib/systemd/system/tunaos-countme.timer \
	/etc/bootc-installer/recipe.json; do
	[[ -f "$tokenized" ]] || continue
	if grep -q '@TUNAOS_[A-Z_]*@' "$tokenized"; then
		leftover+=" ${tokenized}"
	fi
done
if [[ -n "$leftover" ]]; then
	fail "unrendered @TUNAOS_*@ identity token in:${leftover}"
else
	pass "no unrendered identity tokens"
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
	# The expected namespace is the one 90-image-info.sh resolved from the
	# same publish configuration and persisted. A fork that publishes to
	# its own namespace is stamped with it, so a fixed 'tuna-os' here
	# failed every zero-config fork desktop build. Build time also holds
	# the resolved IMAGE_VENDOR; it must agree with the persisted value.
	vendor_file=/usr/share/tunaos/image-vendor
	want_vendor=""
	[[ -r "$vendor_file" ]] && want_vendor="$(head -n 1 "$vendor_file")"
	if [[ -z "$want_vendor" ]]; then
		fail "no persisted publish namespace at ${vendor_file} (90-image-info.sh did not run)"
	elif [[ -n "${IMAGE_VENDOR:-}" && "${IMAGE_VENDOR}" != "$want_vendor" ]]; then
		fail "persisted namespace '${want_vendor}' disagrees with build IMAGE_VENDOR '${IMAGE_VENDOR}'"
	elif [[ "$jvendor" == "$want_vendor" ]]; then
		pass "image-vendor=${jvendor}"
	else
		fail "image-vendor is '${jvendor}', want '${want_vendor}'"
	fi
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

# Plymouth: the boot splash is the first branded thing a user sees. This is a
# presence floor only: every variant ships the tunaos theme, so it cannot tell
# one variant's splash from another's. Which theme the initramfs actually draws
# is proven by checks/verify-plymouth-initramfs.sh (tunaOS#4104).
if [[ -d /usr/share/plymouth/themes/tunaos ]] ||
	[[ "$(readlink -f /usr/share/plymouth/themes/default.plymouth 2>/dev/null)" == *tunaos* ]]; then
	pass "TunaOS plymouth themes installed (presence only; not the selected theme)"
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
if [[ "$mode" != --runtime ]]; then
	if [[ "$fails" -gt 0 ]]; then
		echo "TUNAOS_BRANDING_FAIL variant=${variant} failures=${fails}" | tee /dev/ttyS0 2>/dev/null || true
		marker_emitted=1
		exit 1
	fi
	echo "TUNAOS_BRANDING_OK variant=${variant}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 0
fi

# ------------------------------------------------------------------ runtime --

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
runtime_lib="${here}/verify-branding-runtime.sh"
if [[ ! -r "$runtime_lib" ]]; then
	echo "TUNAOS_BRANDING_FAIL variant=${variant} desktop=${desktop} failed=checker_incomplete reason=missing_${runtime_lib##*/}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
# shellcheck source=verify-branding-runtime.sh
source "$runtime_lib"
set +e

if [[ "$fails" -gt 0 ]]; then
	_image_detail="$(printf '%s; ' "${fail_messages[@]}")"
	record image fail "${fails} layer 1/2 finding(s): ${_image_detail%; }"
else
	record image pass "identity, logos, tokens, image-info.json and assets"
fi

echo "== runtime =="
check_os_release
check_hostname
check_boot_bls
check_boot_efi
check_initramfs_plymouth
check_flatpak_remotes
check_installer_catalog
check_fastfetch
check_issue

# The per-desktop checker takes the CANONICAL variant (identity.env), which
# differs from the publish name for bonito-rawhide.
canonical="$(sed -n "s/^TUNAOS_VARIANT=//p" "${R}/usr/share/tunaos/identity.env" 2>/dev/null | tr -d "'\"" | head -1)"
desktop_checker=""
case "$desktop" in
base) ;;
gnome | tuna) desktop_checker=gnome ;;
kde | niri | cosmic | xfce | pantheon) desktop_checker="$desktop" ;;
*) record "desktop.${desktop}" fail "no branding checker for desktop '${desktop}'" ;;
esac
if [[ -n "$desktop_checker" ]]; then
	checker=""
	for candidate in "${here}/verify-branding-${desktop_checker}" "${here}/verify-branding-${desktop_checker}.sh"; do
		[[ -x "$candidate" ]] && checker="$candidate" && break
	done
	if [[ -z "$checker" ]]; then
		record "desktop.${desktop}" fail "verify-branding-${desktop_checker} is not installed next to ${BASH_SOURCE[0]}"
	else
		echo "== desktop: ${desktop} (${checker##*/}) =="
		sub_out="$(TUNAOS_BRANDING_DESKTOP="$desktop" "$checker" "${canonical:-$variant}" --runtime 2>&1)"
		sub_rc=$?
		printf '%s\n' "$sub_out"
		sub_fails="$(grep -E '^[[:space:]]*FAIL:' <<<"$sub_out" | sed -E 's/^[[:space:]]*FAIL:[[:space:]]*//' | paste -sd ';' -)"
		if [[ "$sub_rc" -eq 0 ]]; then
			record "desktop.${desktop}" pass "$(grep -E '^TUNAOS_BRANDING_[A-Z]+_OK' <<<"$sub_out" | tail -1)"
		else
			record "desktop.${desktop}" fail "${sub_fails:-${checker##*/} exited ${sub_rc}}"
		fi
	fi
	check_user_look "$desktop"
fi

# Companion checkers that ship with their writer and are installed by the
# desktop stage: GNOME Initial Setup's accent and Ubuntu pages (tunaOS#4408,
# verify-gnome-initial-setup) and the DMS greeter's wallpaper and mark
# (verify-dms-greeter). An image built before its checker has none, which is
# reported as skip, not assumed.
companion() { # <check id> <checker> <OK marker prefix>
	local id="$1" checker="${here}/$2" ok="$3" out rc line
	if [[ ! -x "$checker" ]]; then
		record "$id" skip "$2 is not installed in this image"
		return
	fi
	out="$("$checker" "${canonical:-$variant}" --runtime 2>&1)"
	rc=$?
	printf '%s\n' "$out"
	line="$(grep -E "^${ok%_OK}_(OK|FAIL)" <<<"$out" | tail -1)"
	if [[ "$rc" -eq 0 && "$line" == "$ok"* ]]; then
		record "$id" pass "$line"
	else
		record "$id" fail "${line:-$2 exited ${rc}}"
	fi
}
case "$desktop" in
gnome | tuna) companion "desktop.${desktop}.initial-setup" verify-gnome-initial-setup TUNAOS_INITIAL_SETUP_OK ;;
niri) companion desktop.niri.greeter verify-dms-greeter TUNAOS_DMS_GREETER_OK ;;
esac

failed_ids=()
skipped=0
checks_json=""
for id in "${BRANDING_CHECK_IDS[@]}"; do
	status="${BRANDING_CHECK_STATUS[$id]}"
	[[ "$status" == fail ]] && failed_ids+=("$id")
	[[ "$status" == skip ]] && skipped=$((skipped + 1))
	checks_json+="${checks_json:+,}{\"id\":$(json_str "$id"),\"status\":$(json_str "$status"),\"detail\":$(json_str "${BRANDING_CHECK_DETAIL[$id]}")}"
done
result=ok
[[ "${#failed_ids[@]}" -eq 0 ]] || result=fail
failed_json=""
for id in "${failed_ids[@]}"; do failed_json+="${failed_json:+,}$(json_str "$id")"; done
report="{\"schema\":1,\"variant\":$(json_str "$variant"),\"canonical\":$(json_str "$canonical"),\"name\":$(json_str "$(osr PRETTY_NAME)"),\"desktop\":$(json_str "$desktop"),\"kernel\":$(json_str "${TUNAOS_BRANDING_KVER:-$(uname -r)}"),\"result\":\"${result}\",\"failed\":[${failed_json}],\"checks\":[${checks_json}]}"

echo
# One write per line, so the JSON reaches ttyS0 in a single piece.
printf 'TUNAOS_BRANDING_REPORT %s\n' "$report" | tee /dev/ttyS0 2>/dev/null || true
if [[ "$result" == fail ]]; then
	_ids="${failed_ids[*]}"
	echo "TUNAOS_BRANDING_FAIL variant=${variant} desktop=${desktop} failed=${_ids// /,}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_OK variant=${variant} desktop=${desktop} checks=${#BRANDING_CHECK_IDS[@]} skipped=${skipped}" | tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
