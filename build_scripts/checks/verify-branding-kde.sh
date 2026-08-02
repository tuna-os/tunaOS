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

marker_emitted=0
trap 'rc=$?; if [[ "$mode" == --runtime && $rc -ne 0 && $marker_emitted -eq 0 ]]; then
	echo "TUNAOS_BRANDING_KDE_FAIL variant=${variant} reason=early_exit rc=${rc}" | tee /dev/ttyS0 2>/dev/null || true
fi' EXIT

fails=0
fail() {
	echo "  FAIL: $*" >&2
	fails=$((fails + 1))
}
pass() { echo "  ok: $*"; }

LNF=/usr/share/plasma/look-and-feel
WP=/usr/share/wallpapers

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
default_lnf="$(grep -rh '^LookAndFeelPackage=' /etc/xdg/kdeglobals /usr/share/kde-settings/kde-profile/default/etc/xdg/kdeglobals 2>/dev/null | head -1 | cut -d= -f2- || true)"
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
# SDDM is what a user sees before Plasma starts. Ours ships no themes at all,
# so the login screen is stock regardless of what the session looks like.
#
# KDE 6.5+ renames SDDM to plasma-login-manager, and the theme and config
# directories move with it (/usr/share/plasmalogin/themes,
# /etc/plasmalogin.conf.d). Both names are in the wild — yellowfin:kde shipped
# sddm in July 2026 and plasmalogin days later — so look in every candidate
# location rather than detecting which DM is installed. A directory that does
# not exist simply contributes nothing.
theme_dirs=(/usr/share/sddm/themes /usr/share/plasmalogin/themes)
conf_paths=(
	/etc/sddm.conf.d/ /usr/lib/sddm/sddm.conf.d/ /etc/sddm.conf
	/etc/plasmalogin.conf.d/ /usr/lib/plasmalogin.conf.d/ /etc/plasmalogin.conf
)

if compgen -G "/usr/share/sddm/themes/*tuna*" >/dev/null ||
	compgen -G "/usr/share/plasmalogin/themes/*tuna*" >/dev/null; then
	pass "TunaOS greeter theme present"
else
	have=$(ls "${theme_dirs[@]}" 2>/dev/null | tr '\n' ' ' || true)
	fail "no TunaOS SDDM/plasmalogin theme — only: ${have:-<none, directory is empty>}"
fi

greeter_theme="$(grep -rh '^Current=' "${conf_paths[@]}" 2>/dev/null | head -1 | cut -d= -f2- || true)"
if [[ -z "$greeter_theme" ]]; then
	fail "no SDDM/plasmalogin Current= theme configured"
elif [[ "$greeter_theme" != *tuna* ]]; then
	fail "greeter Current=${greeter_theme} — not ours"
else
	pass "greeter Current=${greeter_theme}"
fi

echo
if [[ "$fails" -gt 0 ]]; then
	echo "TUNAOS_BRANDING_KDE_FAIL variant=${variant} failures=${fails}" | tee /dev/ttyS0 2>/dev/null || true
	marker_emitted=1
	exit 1
fi
echo "TUNAOS_BRANDING_KDE_OK variant=${variant}" | tee /dev/ttyS0 2>/dev/null || true
marker_emitted=1
