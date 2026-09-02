#!/bin/bash
# TAP-style installer GUI verification checks for the live-image smoke
# workflows. Runs INSIDE the live guest via SSH (uploaded alongside
# lib/e2e-assert.sh by scripts/iso-e2e.sh or directly by
# installer-smoke.yml).
#
# Verifies, per desktop flavor:
#   1. The right compositor is running (not stuck at a greeter / TTY fallback)
#   2. The correct installer flatpak frontend launched
#   3. The installer wrote a readiness stamp (a window reached the screen)
#   4. The stamp's app_id matches the expected frontend
#
# Usage (inside guest):
#   FLAVOR=kde bash e2e-installer-gui-checks.sh
#
# Output: TAP (ok / not ok), exit code = number of failures.
#
# Pattern: frostyard/snosi tiered-check style, same as e2e-smoke-checks.sh
# and e2e-luks-checks.sh, adapted from installer-smoke.yml's inline
# verification steps (tunaOS#678).
set -uo pipefail

# `/lib` belongs INSIDE the default, not after the expansion. iso-e2e.sh
# uploads the helper flat, next to this script:
#
#   scp scripts/lib/e2e-assert.sh guest:${GUEST_HOME}/e2e-assert.sh
#   ssh  TEST_LIB_DIR=${GUEST_HOME} bash ${GUEST_HOME}/e2e-installer-gui-checks.sh
#
# so with TEST_LIB_DIR set, `${TEST_LIB_DIR}/lib/e2e-assert.sh` names a
# directory the guest does not have. This script has therefore NEVER run:
# smoke run 32681262659 shows every assertion missing, not failing --
#
#   /home/liveuser/e2e-installer-gui-checks.sh: line 25:
#     /home/liveuser/lib/e2e-assert.sh: No such file or directory
#   /home/liveuser/e2e-installer-gui-checks.sh: line 54: check: command not found
#   ...
#   line 159: print_summary: command not found
#
# and the harness reported "installer GUI checks reported 127 failure(s)".
# 127 is bash for command-not-found, not a count of anything. The sibling
# scripts get this right two different ways (e2e-luks-checks.sh has no /lib
# at all; e2e-smoke-checks.sh puts it inside the default), which is how the
# odd one out survived.
HELPERS="${TEST_LIB_DIR:-$(dirname "$0")/lib}/e2e-assert.sh"
# A missing helper must be LOUD. Sourcing a file that is not there leaves
# check() undefined, and every assertion then "passes" by printing nothing to
# stdout while bash writes command-not-found to stderr -- a gate that examines
# nothing and reports success is worse than one that fails.
if [[ ! -r "$HELPERS" ]]; then
	echo "Bail out! cannot read assertion helpers at ${HELPERS}"
	exit 99
fi
# shellcheck source=scripts/lib/e2e-assert.sh
source "$HELPERS"

FLAVOR="${FLAVOR:-gnome}"
echo "# Installer GUI checks — flavor=${FLAVOR}"

# ── 1. Compositor is the right one for this flavor ─────────────────────────
# Ground truth: the compositor binary for THIS flavor is actually running.
# A generic check accepts any compositor, so a stale Wayland socket or a
# cosmic-greeter's cosmic-comp can masquerade as a real desktop.
case "${FLAVOR}" in
	kde)    COMPS="kwin_wayland" ;;
	cosmic) COMPS="cosmic-comp" ;;
	niri)   COMPS="niri" ;;
	xfce)   COMPS="xfwl4 labwc wayfire xfwm4" ;;
	gnome)  COMPS="gnome-shell" ;;
	*)      echo "not ok - unsupported installer flavor: ${FLAVOR}"
	        FAIL=$((FAIL + 1))
	        print_summary
	        ;;
esac

compositor_found=""
for p in $COMPS; do
	if pgrep -x "$p" >/dev/null 2>&1; then
		compositor_found="$p"
		break
	fi
done

check "compositor running (${COMPS})" \
	test -n "$compositor_found"

if [[ -n "$compositor_found" ]]; then
	echo "#   compositor: ${compositor_found}"
else
	echo "#   no compositor running — stuck at greeter or TTY?"
	echo "#   loginctl sessions:"
	loginctl list-sessions 2>/dev/null | sed 's/^/#     /' || true
	echo "#   display-manager status:"
	systemctl status display-manager.service 2>/dev/null | head -5 | sed 's/^/#     /' || true
fi

# ── 2. The desktop-matched installer frontend is running ────────────────────
# flatpak ps is authoritative: app id, not a substring guess. No pgrep -f
# fallback — it can self-match its own command line and cannot distinguish
# the four frontends from each other.
case "${FLAVOR}" in
	kde)    APP=org.tunaos.InstallerKde ;;
	cosmic) APP=org.tunaos.InstallerCosmic ;;
	niri)   APP=org.tunaos.InstallerNiri ;;
	xfce)   APP=org.tunaos.InstallerXfce ;;
	*)      APP=org.bootcinstaller.Installer ;;
esac

installer_running=""
if command -v flatpak >/dev/null 2>&1; then
	installer_running=$(flatpak ps --columns=application 2>/dev/null | grep -Fx "${APP}" || true)
fi

check "installer frontend launched (${APP})" \
	test -n "$installer_running"

if [[ -z "$installer_running" ]]; then
	echo "#   running flatpaks:"
	flatpak ps 2>/dev/null | sed 's/^/#     /' || true
	flatpak list --app --columns=application 2>/dev/null | sed 's/^/#     /' || true
	echo "#   autostart entries:"
	ls -la /etc/xdg/autostart/ 2>/dev/null | sed 's/^/#     /' || true
fi

# ── 3. The installer wrote a readiness stamp ────────────────────────────────
# "process alive" ≠ "window on screen". Each frontend writes
# $XDG_RUNTIME_DIR/tuna-installer-ready when its window comes up.
#
# THE SANDBOX PATH WAS MISSING HERE, AND ONLY HERE. installer-smoke.yml's
# inline copy of this same check was corrected (3c6cbf0c, "read the stamp
# where flatpak actually puts it"); this script does the identical job over
# SSH and was left behind. Two copies of one check, one of them fixed.
#
# Inside the sandbox $XDG_RUNTIME_DIR reads as /run/user/<uid>, but that is a
# BIND MOUNT and the host path differs. Current flatpak backs it with
#   /run/user/<uid>/.flatpak/<app-id>/xdg-run/
# The app/<app-id>/ directory still EXISTS -- flatpak creates it -- so its
# emptiness looked like proof that nothing had been written, which is how this
# survived.
#
# Measured, kde run 32718219267: this script reported
#   not ok - installer readiness stamp present
# while the workflow's inline check, on the same guest at the same moment,
# read the stamp and printed
#   app_id=org.tunaos.InstallerKde window=ApplicationWindow
#   signal=frame-swapped page=welcome
# A frame HAD been swapped and the window WAS on screen. The failure was the
# lookup, not the installer.
#
# All three paths, newest layout first: an unsandboxed run still writes to
# /run/user/<uid>/ directly, and app/<app-id>/ costs nothing to keep for
# older flatpak.
STAMP=""
for d in /run/user/*/.flatpak/"${APP}"/xdg-run/tuna-installer-ready \
	/run/user/*/app/"${APP}"/tuna-installer-ready \
	/run/user/*/tuna-installer-ready; do
	if [[ -f "$d" ]]; then
		STAMP=$(cat "$d" 2>/dev/null | head -20)
		break
	fi
done

check "installer readiness stamp present" \
	test -n "$STAMP"

if [[ -n "$STAMP" ]]; then
	echo "# readiness stamp:"
	echo "$STAMP" | sed 's/^/#   /'

	# ── 4. The stamp comes from the frontend we asked for ──────────────────
	STAMP_APP=$(echo "$STAMP" | sed -n 's/^app_id=//p' | head -1)
	check "readiness stamp app_id matches (expected ${APP})" \
		test "$STAMP_APP" = "${APP}"

	# ── 5. The signal is one we understand ─────────────────────────────────
	STAMP_SIGNAL=$(echo "$STAMP" | sed -n 's/^signal=//p' | head -1)
	case "${STAMP_SIGNAL}" in
		frame-swapped|gtk-map)
			echo "#   signal: ${STAMP_SIGNAL} — window confirmed on screen"
			;;
		first-frame)
			echo "#   signal: ${STAMP_SIGNAL} — app producing frames"
			echo "#   (libcosmic's strongest claim; does not prove a surface was presented)"
			;;
		*)
			echo "not ok - unrecognised readiness signal '${STAMP_SIGNAL:-<none>}'"
			echo "#   add it or fix the frontend"
			FAIL=$((FAIL + 1))
			;;
	esac
else
	echo "#   runtime dirs for debugging:"
	ls -la /run/user/*/ /run/user/*/app/*/ 2>/dev/null | head -20 | sed 's/^/#     /' || true
fi

# ── 6. Installer binary/entrypoint is present ──────────────────────────────
# Not a behavioural check, but confirms the image actually ships the frontend
# it claims. A missing flatpak is a build failure, not a GUI failure, and
# catching it here distinguishes "image is broken" from "GUI didn't start".
case "${FLAVOR}" in
	kde)    check "installer flatpak is installed (${APP})" \
		flatpak list --app --columns=application 2>/dev/null | grep -qFx "${APP}" ;;
	cosmic) check "installer flatpak is installed (${APP})" \
		flatpak list --app --columns=application 2>/dev/null | grep -qFx "${APP}" ;;
	niri)   check "installer flatpak is installed (${APP})" \
		flatpak list --app --columns=application 2>/dev/null | grep -qFx "${APP}" ;;
	xfce)   check "installer flatpak is installed (${APP})" \
		flatpak list --app --columns=application 2>/dev/null | grep -qFx "${APP}" ;;
	*)      check "installer flatpak is installed (${APP})" \
		flatpak list --app --columns=application 2>/dev/null | grep -qFx "${APP}" ;;
esac

print_summary
