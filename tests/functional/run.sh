#!/usr/bin/env bash
# tests/functional/run.sh — tier-1 functional checks for a booted TunaOS image
# (tuna-os/tunaos#576).
#
# The publish boot gate proves an image *boots*; this suite proves features a
# user actually needs are present and working on the RUNNING system. Run it
# over SSH against a booted image (corral VM, QEMU gate VM, or a local
# install). It asserts per-desktop expectations and generic image health:
#
#   1. system is running (or degraded) and graphical.target is reached
#   2. no failed systemd units outside a VM-noise allowlist
#   3. the display manager expected for the desktop is active
#   4. the desktop's session binary and a session entry are present
#   5. bootc status is healthy
#   6. Flathub remote is configured (system/user remotes or remotes.d preconfig)
#   7. variant branding: image-info.json + installer recipe.json (when variant given)
#   8. composefs mounted (when FUNCTIONAL_EXPECT_COMPOSEFS=1)
#   9. Homebrew available (when brew-setup.service exists)
#
# Output is TAP-like (ok/not ok); the exit code is the failure count, so SSH
# returns it directly to the caller.
#
# Usage:
#   tests/functional/run.sh <desktop> [variant]
#     desktop: gnome|kde|niri|cosmic|xfce|pantheon
#     variant: yellowfin|albacore|... — enables the branding assertions
#
# Environment:
#   FUNCTIONAL_ROOT            prefix for filesystem reads (tests only)
#   FUNCTIONAL_FAILED_ALLOWLIST  extra space-separated units to allow
#   FUNCTIONAL_EXPECT_COMPOSEFS  "1" to require composefs/erofs in /proc/mounts
set -uo pipefail

DESKTOP="${1:?usage: $0 <desktop> [variant] — desktop: gnome|kde|niri|cosmic|xfce|pantheon}"
VARIANT="${2:-}"

# TAP helpers: check "desc" cmd..., then print_summary (exits with failure count).
# shellcheck source=../../scripts/lib/e2e-assert.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/scripts/lib/e2e-assert.sh"

ROOT="${FUNCTIONAL_ROOT:-}"

# ── Per-desktop expectation map ─────────────────────────────────────────────
# Mirrors build_scripts/checks/verify-desktop-experience.sh: same DM patterns,
# session binaries, and session-entry globs, so the functional suite and the
# in-image desktop contract agree on what a healthy desktop looks like.
case "${DESKTOP}" in
gnome)
	DM_PATTERN='^(gdm|gdm3)\.service$'
	SESSION_BIN=gnome-shell
	SESSION_GLOBS='/usr/share/wayland-sessions/*gnome*.desktop /usr/share/wayland-sessions/ubuntu*.desktop'
	;;
kde)
	DM_PATTERN='^(sddm|plasmalogin)\.service$'
	SESSION_BIN=plasmashell
	SESSION_GLOBS='/usr/share/wayland-sessions/*plasma*.desktop'
	;;
niri)
	DM_PATTERN='^greetd\.service$'
	SESSION_BIN=niri
	SESSION_GLOBS='/usr/share/wayland-sessions/*niri*.desktop'
	;;
cosmic)
	DM_PATTERN='^(greetd|cosmic-greeter)\.service$'
	SESSION_BIN=cosmic-comp
	SESSION_GLOBS='/usr/share/wayland-sessions/*cosmic*.desktop'
	;;
xfce)
	DM_PATTERN='^(gdm|gdm3|lightdm|greetd)\.service$'
	SESSION_BIN=xfce4-session
	SESSION_GLOBS='/usr/share/xsessions/*xfce*.desktop /usr/share/wayland-sessions/*xfce*.desktop'
	;;
pantheon)
	DM_PATTERN='^lightdm\.service$'
	SESSION_BIN=gala
	SESSION_GLOBS='/usr/share/xsessions/pantheon*.desktop /usr/share/wayland-sessions/pantheon*.desktop'
	;;
*)
	echo "unknown desktop: ${DESKTOP} (want gnome|kde|niri|cosmic|xfce|pantheon)" >&2
	exit 2
	;;
esac

# VM-environment failed units that a healthy desktop image legitimately ships
# with (observed in the #576 manual run): extend via FUNCTIONAL_FAILED_ALLOWLIST.
ALLOWLIST="libstoragemgmt.service mcelog.service ${FUNCTIONAL_FAILED_ALLOWLIST:-}"

echo "# Functional checks — ${DESKTOP}${VARIANT:+ (${VARIANT})}"

# ── 1. System state ─────────────────────────────────────────────────────────
sys_state="$(systemctl is-system-running 2>/dev/null || true)"
echo "# systemctl is-system-running: ${sys_state}"
check "system is running or degraded" \
	bash -c "[[ '${sys_state}' == running || '${sys_state}' == degraded ]]"
check "graphical.target is active" systemctl is-active graphical.target

# ── 2. Failed units (allowlist-filtered) ────────────────────────────────────
failed_units=()
while read -r unit _; do
	[[ -n "${unit}" ]] && failed_units+=("${unit}")
done < <(systemctl --failed --no-legend 2>/dev/null)
blocking=()
for unit in "${failed_units[@]}"; do
	if [[ " ${ALLOWLIST} " == *" ${unit} "* ]]; then
		echo "# allowlisted failed unit: ${unit}"
	else
		blocking+=("${unit}")
	fi
done
if [[ ${#blocking[@]} -gt 0 ]]; then
	echo "# blocking failed units: ${blocking[*]}"
fi
check "no failed systemd units outside allowlist" \
	test "${#blocking[@]}" -eq 0

# ── 3. Display manager ──────────────────────────────────────────────────────
dm_id="$(systemctl show -P Id display-manager.service 2>/dev/null || true)"
echo "# display-manager.service Id: ${dm_id}"
check "display-manager.service is active" systemctl is-active display-manager.service
check "display manager matches ${DESKTOP} (${DM_PATTERN})" \
	bash -c "[[ '${dm_id}' =~ ${DM_PATTERN} ]]"

# ── 4. Session binary + entry ───────────────────────────────────────────────
check "${SESSION_BIN} is installed" bash -c "command -v ${SESSION_BIN}"
session_found=0
for glob in ${SESSION_GLOBS}; do
	compgen -G "${ROOT}${glob}" >/dev/null 2>&1 && session_found=1
done
check "a ${DESKTOP} session entry exists" test "${session_found}" -eq 1

# ── 5. bootc health ─────────────────────────────────────────────────────────
check "bootc status is healthy" bootc status

# ── 6. Flatpak / Flathub ────────────────────────────────────────────────────
# The image preconfigures /etc/flatpak/remotes.d/flathub.flatpakrepo, but the
# remote can materialize per-user only; accept either signal (see #576 notes).
has_remote="$(flatpak remotes --columns=name 2>/dev/null | grep -cx 'flathub' || true)"
has_preconfig=0
compgen -G "${ROOT}/etc/flatpak/remotes.d/flathub.flatpakrepo" >/dev/null 2>&1 && has_preconfig=1
echo "# flathub: remote=${has_remote} preconfig=${has_preconfig}"
check "Flathub remote is configured" \
	bash -c "[[ ${has_remote} -ge 1 || ${has_preconfig} -eq 1 ]]"

# ── 7. Variant branding ─────────────────────────────────────────────────────
if [[ -n "${VARIANT}" ]]; then
	info="${ROOT}/usr/share/ublue-os/image-info.json"
	check "image-info.json exists" test -f "${info}"
	if [[ -f "${info}" ]]; then
		jname="$(python3 -c "import json;print(json.load(open('${info}')).get('image-name',''))" 2>/dev/null || true)"
		check "image-info.json image-name is ${VARIANT}" test "${jname}" = "${VARIANT}"
		jvendor="$(python3 -c "import json;print(json.load(open('${info}')).get('image-vendor',''))" 2>/dev/null || true)"
		check "image-info.json image-vendor is tuna-os" test "${jvendor}" = "tuna-os"
	fi
	check "installer recipe.json exists" test -f "${ROOT}/etc/bootc-installer/recipe.json"
fi

# ── 8. Composefs (opt-in; e.g. grouper) ─────────────────────────────────────
if [[ "${FUNCTIONAL_EXPECT_COMPOSEFS:-0}" == "1" ]]; then
	check "composefs is mounted" bash -c "grep -qE 'composefs|erofs' /proc/mounts"
fi

# ── 9. Homebrew (when the image ships brew-setup.service) ────────────────────
# brew-setup.service is safe_enable'd in 40-services.sh, meaning it is enabled
# when the unit exists and silently skipped otherwise. A variant without the
# unit is not expected to have brew; assert it only on images that ship it.
if systemctl list-unit-files brew-setup.service --no-legend 2>/dev/null | grep -q '^brew-setup.service'; then
	check "brew is available" bash -c "command -v brew"
fi

print_summary
