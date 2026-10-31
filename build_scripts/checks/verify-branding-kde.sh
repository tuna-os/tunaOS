#!/usr/bin/env bash
# KDE/Plasma branding contract.
#
# WHY THIS EXISTS — measured, not assumed
#
# Aurora (ghcr.io/ublue-os/aurora:latest), the KDE sibling of Bluefin and our
# reference for what a branded Plasma image looks like:
#
#   /usr/share/plasma/look-and-feel/
#       dev.getaurora.aurora.desktop        <- its OWN look-and-feel package
#       dev.getaurora.auroralight.desktop   <- and a light variant
#       org.fedoraproject.fedora.desktop
#       org.kde.breeze.desktop  ...
#   /usr/share/wallpapers/
#       Aurora                              <- its OWN wallpaper
#       Altai Autumn BytheWater ...
#
# Our grouper:kde (published 2026-08-01):
#
#   /usr/share/plasma/look-and-feel/
#       org.kde.breeze.desktop
#       org.kde.breezedark.desktop
#       org.kde.breezetwilight.desktop      <- stock Breeze ONLY
#   /usr/share/wallpapers/
#       Next                                <- stock Plasma default ONLY
#   /usr/share/sddm/themes/                 <- EMPTY
#
# So the Plasma session is entirely unbranded: stock Breeze, stock wallpaper,
# no login theme. A user cannot tell it from upstream KDE.
#
# The look-and-feel package is the load-bearing one: it is what carries the
# colour scheme, splash, lockscreen and default layout as a single switchable
# unit. Setting a wallpaper without it leaves everything else stock.
#
# USAGE
#   verify-branding-kde.sh <variant> [--runtime]

set -euo pipefail

variant="${1:?usage: verify-branding-kde.sh <variant> [--runtime]}"
mode="${2:-build}"
asset_root="${TUNAOS_BRANDING_ROOT:-}"
require_branded="${TUNAOS_REQUIRE_BRANDED_GREETER:-0}"

marker_emitted=0
emit_fail_on_early_exit() {
	local rc=$?
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		echo "TUNAOS_BRANDING_KDE_FAIL variant=${variant} reason=early_exit rc=${rc}" | tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap emit_fail_on_early_exit EXIT

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

LNF="${asset_root}/usr/share/plasma/look-and-feel"
WP="${asset_root}/usr/share/wallpapers"

echo "== look-and-feel =="
# Aurora ships dev.getaurora.*; ours must ship an equivalent under a TunaOS id.
if compgen -G "${LNF}/*tunaos*" >/dev/null || compgen -G "${LNF}/*tuna-os*" >/dev/null; then
	pass "TunaOS look-and-feel package present"
	# A dark and a light variant, as Aurora ships both. A single theme means
	# the Plasma appearance switcher has nothing to switch to.
	n=$(compgen -G "${LNF}/*tuna*" | wc -l)
	[[ "$n" -ge 2 ]] && pass "${n} TunaOS look-and-feel variants" ||
		fail "only ${n} TunaOS look-and-feel package (Aurora ships light + dark)"
else
	have=$(ls "${LNF}" 2>/dev/null | tr '\n' ' ' || true)
	fail "no TunaOS look-and-feel package — only: ${have:-<none>}"
fi

# The default must actually BE ours. A theme that ships but is not selected
# leaves every user on Breeze.
default_lnf="$(grep -rh '^LookAndFeelPackage=' "${asset_root}/etc/xdg/kdeglobals" "${asset_root}/usr/share/kde-settings/kde-profile/default/xdg/kdeglobals" 2>/dev/null | head -1 | cut -d= -f2- || true)"
if [[ -z "$default_lnf" ]]; then
	fail "no LookAndFeelPackage= default set — users land on Breeze"
elif [[ "$default_lnf" != *tuna* ]]; then
	fail "LookAndFeelPackage=${default_lnf} — not a TunaOS theme"
else
	pass "LookAndFeelPackage=${default_lnf}"
fi

echo "== wallpaper =="
if compgen -G "${WP}/*[Tt]una*" >/dev/null; then
	pass "TunaOS wallpaper package present"
else
	have=$(ls "${WP}" 2>/dev/null | tr '\n' ' ' || true)
	fail "no TunaOS wallpaper in ${WP} — only: ${have:-<none>}"
fi

echo "== login screen =="
# Installation and branded identity are separate capabilities. A stock fallback
# remains usable but cannot qualify branded-greeter. Only a caller explicitly
# requiring that capability makes an unsupported fallback a build failure.
greeter_status=unsupported
greeter_reason="stock-fallback"
found_greeter=""
active_dm=""
if [[ -L "${asset_root}/etc/systemd/system/display-manager.service" ]]; then
	active_dm="$(basename "$(readlink "${asset_root}/etc/systemd/system/display-manager.service")" .service)"
fi
# Match the selected unit, or the repository's PlasmaLogin-before-SDDM policy
# when the build has not linked display-manager.service yet.
for dm in plasmalogin sddm; do
	[[ -z "$active_dm" || "$active_dm" == "$dm" ]] || continue
	if [[ ! -x "${asset_root}/usr/bin/${dm}" &&
		! -f "${asset_root}/usr/lib/systemd/system/${dm}.service" &&
		! -f "${asset_root}/lib/systemd/system/${dm}.service" ]]; then
		continue
	fi
	found_greeter="$dm"
	# SDDM precedence: vendor snippets, administrator snippets, main config.
	# Read [Theme] only, with the last assignment winning.
	configs=()
	for dir in "/usr/lib/${dm}/${dm}.conf.d" "/usr/share/${dm}/${dm}.conf.d" "/usr/lib/${dm}.conf.d" "/etc/${dm}.conf.d"; do
		for conf in "${asset_root}${dir}/"*.conf; do
			[[ ! -f "$conf" ]] || configs+=("$conf")
		done
	done
	[[ ! -f "${asset_root}/etc/${dm}.conf" ]] || configs+=("${asset_root}/etc/${dm}.conf")
	current=""
	if [[ "${#configs[@]}" -gt 0 ]]; then
		current="$(awk '
			FNR == 1 {section=""}
			/^[[:space:]]*\[/ {section=$0; gsub(/[[:space:]]/, "", section)}
			section == "[Theme]" && /^[[:space:]]*Current[[:space:]]*=/ {
				value=$0; sub(/^[^=]*=[[:space:]]*/, "", value); sub(/[[:space:]]*$/, "", value)
			} END {print value}' "${configs[@]}")"
	fi
	if [[ "$current" != breeze ]]; then
		greeter_reason="stock-or-unverified-theme"
		break
	fi
	theme="${asset_root}/usr/share/${dm}/themes/breeze"
	if [[ ! -f "${theme}/Main.qml" ]]; then
		greeter_status=blocked
		greeter_reason="selected-theme-missing"
		break
	fi
	identity="${asset_root}/usr/share/tunaos/identity.env"
	canonical="$(awk -F"'" '$1 == "TUNAOS_VARIANT=" {print $2; exit}' "$identity" 2>/dev/null || true)"
	if [[ "$canonical" != "$variant" || ! "$canonical" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
		fail "canonical variant=${canonical:-missing} does not match requested variant=${variant}"
		greeter_status=blocked
		greeter_reason="canonical-variant-mismatch"
		break
	fi
	wallpaper=""
	for candidate in "${canonical}-kde.jpg" "${canonical}-anime.jpg" "${canonical}.jpg"; do
		if [[ -f "${asset_root}/usr/share/backgrounds/tunaos/${candidate}" ]]; then
			wallpaper="/usr/share/backgrounds/tunaos/${candidate}"
			break
		fi
	done
	# Validate effective Breeze keys, including administrator overrides. A valid
	# sibling SVG or wallpaper at a real path is not canonical identity.
	valid=1
	for entry in "logo:/usr/share/tunaos/lettermarks/${canonical}.svg" "background:${wallpaper}" "showlogo:shown" "type:image"; do
		key="${entry%%:*}"
		expected="${entry#*:}"
		theme_configs=()
		for conf in "${theme}/theme.conf" "${theme}/theme.conf.user"; do
			[[ ! -f "$conf" ]] || theme_configs+=("$conf")
		done
		selected=""
		if [[ "${#theme_configs[@]}" -gt 0 ]]; then
			selected="$(awk -v key="$key" '
				FNR == 1 {section=""}
				/^\[/ {section=$0}
				section == "[General]" && index($0, key "=") == 1 {value=substr($0, length(key)+2)}
				END {print value}' "${theme_configs[@]}")"
		fi
		if [[ "$key" == showlogo || "$key" == type ]]; then
			if [[ "$selected" != "$expected" ]]; then
				fail "${dm} ${key}=${selected}; expected ${expected}"
				valid=0
			fi
			continue
		fi
		if [[ "$selected" != /* || ! -f "${asset_root}${selected}" ||
			! -f "${asset_root}${expected}" ]] || ! cmp -s "${asset_root}${selected}" "${asset_root}${expected}"; then
			fail "${dm} ${key} does not consume canonical asset ${expected}"
			valid=0
		fi
	done
	if [[ "$valid" -eq 1 ]]; then
		greeter_status="config-verified"
		greeter_reason="canonical-assets-selected"
	else
		greeter_status=blocked
		greeter_reason="canonical-asset-mismatch"
	fi
	break
done
if [[ -z "$found_greeter" ]]; then
	fail "no SDDM/plasmalogin binary or unit found — greeter not installed"
	greeter_status=blocked
	greeter_reason="greeter-not-installed"
else
	pass "greeter installed (${found_greeter})"
fi
echo "TUNAOS_BRANDING_KDE_GREETER variant=${variant} status=${greeter_status} reason=${greeter_reason} rendered=not-run"
if [[ "$require_branded" == 1 && "$greeter_status" != config-verified ]]; then
	fail "required branded-greeter capability ${greeter_status}: ${greeter_reason}"
fi

echo
if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_BRANDING_KDE_FAIL variant=${variant} failures=${fails}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_KDE_OK variant=${variant} greeter=${greeter_status} scope=configuration rendered=not-run" | tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
