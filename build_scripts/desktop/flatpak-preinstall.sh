#!/usr/bin/env bash
# flatpak-preinstall.sh — declare the curated Flatpak set for this desktop
# and make sure the mechanism that installs it actually runs.
#
# Sourced by install-desktop.sh via each desktop manifest's post_install
# list, AFTER any desktop-specific script that writes its own preinstall
# file (kcm-ublue.sh writes bazaar.preinstall on dnf KDE images), so the
# already-declared guard below keeps entries unique across files.
#
# WHY. TunaOS images shipped with no browser and — outside dnf KDE and the
# zirconium niri payload — no software store: gnome-software is deliberately
# excluded (manifests/desktops/gnome.yaml), Bazaar's preinstall was written
# only by kcm-ublue.sh (which skips every non-dnf base), and nothing ever
# enabled flatpak-preinstall.service, so even the files that existed were
# inert wherever the distro preset didn't enable the unit. The upstream
# curated experiences this project mirrors do both: Bluefin and Aurora ship
# io.github.kolunmi.Bazaar via /usr/share/flatpak/preinstall.d AND
# `systemctl enable flatpak-preinstall.service` (their 17-cleanup.sh), and
# Bluefin's default browser is the org.mozilla.firefox Flatpak (its GNOME
# favorite-apps pins org.mozilla.firefox.desktop and its setup hook installs
# the Firefox flatpak's systemconfig extension).
#
# The curated set is deliberately small and identical across desktops:
#   io.github.kolunmi.Bazaar   the software store (every desktop; replaces
#                              the excluded gnome-software / hidden discover)
#   org.mozilla.firefox        the browser (every desktop; Bluefin's choice)
# Per-desktop additions belong in the same mechanism: add_app lines guarded
# by _FP_DESKTOP, with a matching assert in verify-desktop-experience.sh —
# assert exactly what is added, nothing aspirational.
#
# Test hooks: TUNAOS_PREINSTALL_DIR and TUNAOS_SYSTEMD_SYSTEM_DIR redirect
# the paths (same pattern as 40-services.sh); systemctl resolves via PATH.

set -euo pipefail

_FP_DIR="${TUNAOS_PREINSTALL_DIR:-/usr/share/flatpak/preinstall.d}"
_FP_UNIT_DIR="${TUNAOS_SYSTEMD_SYSTEM_DIR:-/usr/lib/systemd/system}"
_FP_DESKTOP="${_TD_DESKTOP:-${DESKTOP_FLAVOR:-desktop}}"
_FP_FILE="${_FP_DIR}/tunaos-${_FP_DESKTOP}.preinstall"

mkdir -p "$_FP_DIR"

_fp_declared() {
	grep -rqs "^\[Flatpak Preinstall $1\]" "$_FP_DIR"
}

_fp_add_app() {
	local app="$1"
	if _fp_declared "$app"; then
		echo "flatpak-preinstall: ${app} already declared, skipping"
		return 0
	fi
	{
		echo "[Flatpak Preinstall ${app}]"
		echo "Branch=stable"
		echo "IsRuntime=false"
		echo
	} >>"$_FP_FILE"
	echo "flatpak-preinstall: declared ${app} for ${_FP_DESKTOP}"
}

_fp_add_app io.github.kolunmi.Bazaar
_fp_add_app org.mozilla.firefox

# A preinstall file with nothing to run it is decoration. flatpak ships the
# unit on current Fedora/EL; where a base does not ship it yet, say so
# loudly in the build log instead of failing a family this cannot serve —
# verify-desktop-experience.sh applies the same conditional contract, so a
# base that gains the unit later cannot ship it disabled.
if [[ -f "${_FP_UNIT_DIR}/flatpak-preinstall.service" ]]; then
	systemctl enable flatpak-preinstall.service
	echo "flatpak-preinstall: flatpak-preinstall.service enabled"
else
	echo "WARNING: flatpak-preinstall.service is not shipped by this base's flatpak;" >&2
	echo "         the preinstall declarations in ${_FP_DIR} will not self-install." >&2
fi
