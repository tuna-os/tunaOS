#!/usr/bin/env bash
set -euo pipefail

desktop="${1:?usage: verify-desktop-experience.sh <gnome|kde|niri|cosmic|xfce> [--runtime]}"
mode="${2:-build}"

# At runtime the E2E gate greps ttyS0 for a contract marker; a silent early
# exit (e.g. a require_* failing under set -e) would leave the gate waiting
# out its full timeout with no evidence. Guarantee a terminal FAIL marker on
# any premature death; the normal paths below disarm this trap.
marker_emitted=0
emit_fail_on_early_exit() {
	local rc=$?
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		echo "TUNAOS_DESKTOP_CONTRACT_FAIL desktop=${desktop} reason=early_exit rc=${rc}" | tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap emit_fail_on_early_exit EXIT

require_command() { command -v "$1" >/dev/null || {
	echo "missing required command: $1" >&2
	exit 1
}; }
require_glob() { compgen -G "$1" >/dev/null || {
	echo "missing required path: $1" >&2
	exit 1
}; }
require_unit() { systemctl list-unit-files "$1.service" --no-legend 2>/dev/null | grep -q "^$1.service" || {
	echo "missing unit: $1.service" >&2
	exit 1
}; }
# Distro drift: the same DE ships different DM units per variant (gdm vs
# Debian's gdm3; xfce is gdm on Fedora/EL but lightdm/greetd on Ubuntu).
# Build-time: require at least one candidate unit to exist.
require_any_unit() {
	local u
	for u in "$@"; do
		if systemctl list-unit-files "$u.service" --no-legend 2>/dev/null | grep -q "^$u.service"; then
			return 0
		fi
	done
	echo "missing unit: none of [$*] exist" >&2
	exit 1
}
# Session availability may be wayland or x11 depending on DE/distro.
require_any_glob() {
	local g
	for g in "$@"; do
		compgen -G "$g" >/dev/null && return 0
	done
	echo "missing required path: none of [$*] exist" >&2
	exit 1
}

case "$desktop" in
gnome)
	experience="projectbluefin/bluefin-lts"
	require_command gnome-shell
	require_glob '/usr/share/wayland-sessions/*gnome*.desktop'
	require_any_unit gdm gdm3
	dm_pattern='^(gdm|gdm3)\.service$'
	;;
kde)
	experience="ublue-os/aurora"
	require_command plasmashell
	require_glob '/usr/share/wayland-sessions/*plasma*.desktop'
	require_unit sddm
	dm_pattern='^sddm\.service$'
	;;
niri)
	experience="zirconium-dev/zirconium"
	require_command niri
	require_glob '/usr/share/wayland-sessions/*niri*.desktop'
	require_unit greetd
	dm_pattern='^greetd\.service$'
	;;
cosmic)
	experience="tunaos/cosmic"
	require_command cosmic-comp
	require_glob '/usr/share/wayland-sessions/*cosmic*.desktop'
	require_unit greetd
	dm_pattern='^greetd\.service$'
	;;
xfce)
	experience="tunaos/xfce"
	require_command xfce4-session
	require_any_glob '/usr/share/xsessions/*xfce*.desktop' '/usr/share/wayland-sessions/*xfce*.desktop'
	require_any_unit gdm gdm3 lightdm greetd
	dm_pattern='^(gdm|gdm3|lightdm|greetd)\.service$'
	;;
*) exit 0 ;;
esac

if [[ "$mode" == --runtime ]]; then
	# Each check is individually gated so a single failure doesn't
	# kill the script silently via `set -e`. The final marker is
	# written to the serial console regardless of partial failures.
	ok=1
	report_fail() {
		local reason="$1"
		echo "TUNAOS_DESKTOP_CONTRACT_FAIL reason=${reason}" | tee /dev/ttyS0 2>/dev/null || true
		ok=0
	}
	if ! command -v remora >/dev/null 2>&1; then
		report_fail remora_not_found
	fi
	if ! compgen -G '/usr/share/tunaos/experience-contracts/remora' >/dev/null 2>&1; then
		report_fail remora_contract_missing
	fi
	# NB: never check `is-active graphical.target` here. This service is
	# WantedBy=graphical.target, and targets gain implicit After= on their
	# wants — the target cannot become active until this script exits, so
	# that check self-deadlocks into a guaranteed failure. Assert the boot
	# *default* instead; liveness comes from the display-manager check below.
	if [[ "$(systemctl get-default 2>/dev/null)" != graphical.target ]]; then
		report_fail default_target_not_graphical
	fi
	# Check the display-manager.service alias (every DM registers it) and
	# verify its Id resolves to a DM this desktop's contract allows — robust
	# to per-distro unit names (gdm vs gdm3, lightdm vs greetd for xfce).
	if ! systemctl is-active --quiet display-manager.service 2>/dev/null; then
		report_fail "dm_inactive desktop=$desktop"
	else
		dm_id=$(systemctl show -P Id display-manager.service 2>/dev/null || true)
		if [[ ! "$dm_id" =~ $dm_pattern ]]; then
			report_fail "dm_mismatch dm=${dm_id:-unknown} expected=${dm_pattern}"
		fi
	fi
	if [[ "$ok" -eq 1 ]]; then
		echo "TUNAOS_DESKTOP_CONTRACT_OK desktop=$desktop experience=$experience" | tee /dev/ttyS0 2>/dev/null || true
	fi
	# Always emit a final summary marker (OK or FAIL) so the gate has a
	# deterministic signal regardless of which individual reason fired.
	if [[ "$ok" -eq 0 ]]; then
		echo "TUNAOS_DESKTOP_CONTRACT_FAIL desktop=$desktop" | tee /dev/ttyS0 2>/dev/null || true
	fi
	marker_emitted=1
else
	# ── Static unit-graph validation (pattern from secureblue's
	# validate_systemd_unit_files.sh) ── catches unit typos, missing
	# executables and broken dependency graphs before the image ships.
	# Warn-only by default (upstream units carry pre-existing noise on some
	# variants); SYSTEMD_VERIFY_FATAL=1 enforces, mirroring BOOTC_LINT_FATAL.
	if command -v systemd-analyze >/dev/null 2>&1; then
		verify_rc=0
		systemd-analyze verify --recursive-errors=yes graphical.target || verify_rc=$?
		systemd-analyze verify --user --recursive-errors=yes default.target || verify_rc=$?
		if [[ "$verify_rc" -ne 0 ]]; then
			echo "::warning::systemd-analyze verify reported unit problems (desktop=${desktop})"
			if [[ "${SYSTEMD_VERIFY_FATAL:-0}" -eq 1 ]]; then
				echo "ERROR: SYSTEMD_VERIFY_FATAL=1 and unit verification failed" >&2
				exit 1
			fi
		fi
	fi

	# ── Launcher validation (pattern from ublue-os/aurora's 20-tests.sh) ──
	# desktop-file-validate every shipped launcher; exit code only reflects
	# errors (not warnings), but stock distro apps still carry occasional
	# errors, so warn-only by default with DESKTOP_VALIDATE_FATAL=1 to
	# enforce. Session files are excluded: DesktopNames et al. are legal in
	# session entries but flagged by the validator.
	if command -v desktop-file-validate >/dev/null 2>&1 && compgen -G '/usr/share/applications/*.desktop' >/dev/null; then
		invalid=0
		while IFS= read -r f; do
			if ! desktop-file-validate "$f" >/dev/null 2>&1; then
				echo "invalid desktop file: $f"
				desktop-file-validate "$f" 2>&1 | sed 's/^/  /' || true
				invalid=$((invalid + 1))
			fi
		done < <(find /usr/share/applications -maxdepth 1 -name '*.desktop')
		if [[ "$invalid" -gt 0 ]]; then
			echo "::warning::${invalid} desktop file(s) failed validation (desktop=${desktop})"
			if [[ "${DESKTOP_VALIDATE_FATAL:-0}" -eq 1 ]]; then
				echo "ERROR: DESKTOP_VALIDATE_FATAL=1 and desktop files failed validation" >&2
				exit 1
			fi
		fi
	fi

	# ── KDE version-skew guard (pattern from ublue-os/aurora's 20-tests.sh) ──
	# Mid-compose repo skew can ship kwin/kscreen from a newer Plasma than
	# plasma-desktop; the session then crashes at login while every package
	# transaction "succeeded". Version equality across installed Plasma core
	# packages is a hard invariant on rpm variants — fail the build on skew.
	if [[ "$desktop" == kde ]] && command -v rpm >/dev/null 2>&1; then
		if plasma_ver=$(rpm -q --qf '%{VERSION}' plasma-desktop 2>/dev/null); then
			for pkg in kscreen kwin; do
				if pkg_ver=$(rpm -q --qf '%{VERSION}' "$pkg" 2>/dev/null); then
					if [[ "$plasma_ver" != "$pkg_ver" ]]; then
						echo "ERROR: KDE version skew: plasma-desktop=${plasma_ver} but ${pkg}=${pkg_ver}" >&2
						exit 1
					fi
				fi
			done
		fi
		# Qt skew is the same failure mode one layer down (aurora compares
		# qt6-qtbase against qt6-filesystem as a repo-freshness indicator).
		if qt_ver=$(rpm -q --qf '%{VERSION}' qt6-qtbase 2>/dev/null); then
			if qtfs_ver=$(rpm -q --qf '%{VERSION}' qt6-filesystem 2>/dev/null); then
				if [[ "$qt_ver" != "$qtfs_ver" ]]; then
					echo "ERROR: Qt version skew: qt6-qtbase=${qt_ver} but qt6-filesystem=${qtfs_ver}" >&2
					exit 1
				fi
			fi
		fi
	fi

	install -d /usr/share/tunaos/experience-contracts
	printf 'desktop=%s\nexperience=%s\nvalidated_at_build=true\n' "$desktop" "$experience" \
		>"/usr/share/tunaos/experience-contracts/${desktop}"
	echo "desktop experience contract passed: $desktop ($experience)"
fi
