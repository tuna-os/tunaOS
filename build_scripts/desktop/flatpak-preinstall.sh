#!/usr/bin/env bash
# flatpak-preinstall.sh — declare the curated Flatpak set for this desktop
# and make sure the mechanism that installs it actually runs.
#
# Sourced by install-desktop.sh via each desktop manifest's post_install
# list. The already-declared guard keeps inherited entries unique across
# files. This recipe owns new declarations through primary TOML.
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
# The primary TOML owns the declaration set. Its generated adapter is copied
# into the image so the build/runtime verifier reads the same intended policy.
# These are declarations, not installed inventory or verified remote identity.
# Independent fixture tests pin the pre-migration behavior.
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
	grep -rFxsq -- "[Flatpak Preinstall $1]" "$_FP_DIR"
}

_fp_add_app() {
	local app="$1" branch="$2"
	if _fp_declared "$app"; then
		echo "flatpak-preinstall: ${app} already declared, skipping"
		return 0
	fi
	{
		echo "[Flatpak Preinstall ${app}]"
		echo "Branch=${branch}"
		echo "IsRuntime=false"
		echo
	} >>"$_FP_FILE"
	echo "flatpak-preinstall: declared ${app} for ${_FP_DESKTOP}"
}

_FP_POLICY="$(dirname -- "${BASH_SOURCE[0]}")/flatpak-preinstall.tsv"
[[ -f "$_FP_POLICY" ]] || {
	echo "missing generated Flatpak policy" >&2
	return 1 2>/dev/null || exit 1
}
_FP_INSTALLED_POLICY="${_FP_DIR}/../tunaos-preinstall-policy.tsv"
[[ ! -L "$_FP_INSTALLED_POLICY" ]] || {
	echo "refusing linked Flatpak policy" >&2
	return 1 2>/dev/null || exit 1
}
[[ ! -L "$_FP_FILE" && (! -e "$_FP_FILE" || -f "$_FP_FILE") ]] || {
	echo "refusing non-regular Flatpak declarations" >&2
	return 1 2>/dev/null || exit 1
}
# Reconcile this recipe's own output before the cross-file duplicate guard.
# Otherwise removing an app (including an explicit empty policy) leaves the
# old declaration active when a desktop hook runs again in an inherited layer.
rm -f -- "$_FP_FILE"
: >"$_FP_INSTALLED_POLICY"
chmod 0644 "$_FP_INSTALLED_POLICY"
while IFS=$'\t' read -r _fp_scope _fp_app _fp_branch; do
	[[ "$_fp_scope" == '#'* || -z "$_fp_scope" ]] && continue
	if [[ "$_fp_scope" == '*' || "$_fp_scope" == "$_FP_DESKTOP" ]]; then
		printf '%s\t%s\t%s\n' "$_fp_scope" "$_fp_app" "$_fp_branch" >>"$_FP_INSTALLED_POLICY"
		_fp_add_app "$_fp_app" "$_fp_branch"
	fi
done <"$_FP_POLICY"

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
