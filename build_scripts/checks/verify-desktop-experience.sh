#!/usr/bin/env bash
set -euo pipefail

desktop="${1:?usage: verify-desktop-experience.sh <gnome|kde|niri|cosmic|xfce|pantheon> [--runtime]}"
mode="${2:-build}"

# At runtime the E2E gate greps ttyS0 for a contract marker; a silent early
# exit (e.g. a require_* failing under set -e) would leave the gate waiting
# out its full timeout with no evidence. Guarantee a terminal FAIL marker on
# any premature death; the normal paths below disarm this trap.
marker_emitted=0
emit_fail_on_early_exit() {
	local rc=$?
	if [[ "$mode" == --runtime && "$rc" -ne 0 && "$marker_emitted" -eq 0 ]]; then
		# The static assertions run before the runtime summary block below.  Keep
		# their failure actionable in a serial-only Gate: without this, the
		# harness only gets `early_exit rc=1` and cannot distinguish a missing
		# session, portal, keyring, or display-manager unit.
		local line="${BASH_LINENO[0]:-unknown}"
		local command="${BASH_COMMAND:-unknown}"
		printf 'TUNAOS_DESKTOP_CONTRACT_FAIL desktop=%s reason=early_exit rc=%s line=%s command=%q\n' \
			"${desktop}" "${rc}" "${line}" "${command}" | tee /dev/ttyS0 2>/dev/null || true
	fi
}
trap emit_fail_on_early_exit EXIT

source /run/context/build_scripts/lib.sh 2>/dev/null || true
detected_os 2>/dev/null || true

require_command() { command -v "$1" >/dev/null || {
	echo "missing required command: $1" >&2
	if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then return 0; fi
	exit 1
}; }
require_glob() { compgen -G "$1" >/dev/null || {
	echo "missing required path: $1" >&2
	if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then return 0; fi
	exit 1
}; }
require_unit() { systemctl list-unit-files "$1.service" --no-legend 2>/dev/null | grep -q "^$1.service" || {
	echo "missing unit: $1.service" >&2
	if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then return 0; fi
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
	if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then return 0; fi
	exit 1
}
# Session availability may be wayland or x11 depending on DE/distro.
require_any_glob() {
	local g
	for g in "$@"; do
		compgen -G "$g" >/dev/null && return 0
	done
	echo "missing required path: none of [$*] exist" >&2
	if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then return 0; fi
	exit 1
}

# User systemd units (session services like pipewire, wireplumber, portals).
# Checked via systemctl --user list-unit-files or filesystem unit file globs.
require_user_unit() {
	local u="$1"
	if systemctl --user list-unit-files "$u.service" --no-legend 2>/dev/null | grep -q "^$u.service" ||
		compgen -G "/usr/lib/systemd/user/${u}.service" >/dev/null ||
		compgen -G "/etc/systemd/user/${u}.service" >/dev/null ||
		compgen -G "/usr/lib/*/systemd/user/${u}.service" >/dev/null; then
		return 0
	fi
	echo "missing user unit: ${u}.service" >&2
	if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then return 0; fi
	exit 1
}

require_any_user_unit() {
	local u
	for u in "$@"; do
		if systemctl --user list-unit-files "$u.service" --no-legend 2>/dev/null | grep -q "^$u.service" ||
			compgen -G "/usr/lib/systemd/user/${u}.service" >/dev/null ||
			compgen -G "/etc/systemd/user/${u}.service" >/dev/null ||
			compgen -G "/usr/lib/*/systemd/user/${u}.service" >/dev/null; then
			return 0
		fi
	done
	echo "missing user unit: none of [$*] exist" >&2
	if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then return 0; fi
	exit 1
}

# xfce's greeter is the one desktop piece NO other gate can see missing.
# xfce.sh installs its DM stack via install_available: lightdm first, greetd
# as the fallback â and greetd's stock config runs `agreety --cmd /bin/sh`,
# a text prompt into a bare shell. If gtkgreet (or cage, its kiosk host)
# fails to land, xfce.sh deliberately leaves that stock config in place, the
# installed system still reaches graphical.target with an ACTIVE
# display-manager.service, and both the runtime contract's dm check and the
# LUKS gate read green â xfce.sh's own comment documents the blindness.
# So assert the greeter statically, on exactly the branch xfce.sh's enable
# logic takes: greetd is this image's DM if and only if lightdm did not land.
xfce_greetd_greeter_contract() {
	command -v lightdm >/dev/null 2>&1 && return 0
	command -v greetd >/dev/null 2>&1 || return 0
	require_command gtkgreet
	require_command cage
	local greetd_conf="${TUNAOS_VERIFY_ROOT:-}/etc/greetd/config.toml"
	if ! grep -qs 'gtkgreet' "$greetd_conf"; then
		echo "greetd is the display manager but ${greetd_conf} does not launch gtkgreet â stock agreety boots users to a text prompt, not a login screen" >&2
		if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then return 0; fi
		exit 1
	fi
}

# PORTAL/KEYRING/GVFS PATHS â measured, one container per packaging family.
# Never add a glob you have not seen resolve on a real distro: an invented
# pattern that matches nothing turns a working desktop red, which is exactly
# what '/usr/lib/*/gvfs/gvfsd' did to sailfin and marlin.
#
#   family          gvfsd                          portal-gnome / portal-gtk
#   Fedora / EL     /usr/libexec/gvfsd             /usr/libexec/...
#   Debian/Ubuntu   /usr/libexec/gvfsd AND         /usr/libexec/...
#                   /usr/lib/gvfs/gvfsd
#                   (package is gvfs-daemons, NOT gvfs â plain gvfs ships
#                    only libgvfsdbus.so, so probing gvfs finds nothing)
#   openSUSE        /usr/libexec/gvfs/gvfsd        /usr/libexec/...
#   Arch            /usr/lib/gvfsd                 /usr/lib/...
#
# gnome-keyring-daemon is /usr/bin/gnome-keyring-daemon on all five.
#
case "$desktop" in
gnome)
	experience="projectbluefin/bluefin-lts"
	require_command gnome-shell
	# Ubuntu names its GNOME session `ubuntu.desktop`, not `gnome*.desktop`.
	# Measured on the published grouper:gnome: /usr/share/wayland-sessions
	# contains exactly `ubuntu.desktop`, /usr/share/xsessions does not exist,
	# and gnome-shell IS installed â so the old glob reported a working GNOME
	# desktop as broken. A contract that fails a healthy image is worse than no
	# contract: it trains people to ignore it.
	require_any_glob \
		'/usr/share/wayland-sessions/*gnome*.desktop' \
		'/usr/share/wayland-sessions/ubuntu*.desktop'
	require_any_unit gdm gdm3
	dm_pattern='^(gdm|gdm3)\.service$'
	# Session-can-start is not the same as desktop-is-usable, and the gap
	# between them is exactly how sailfin:gnome shipped. openSUSE's
	# patterns-gnome-gnome provides gnome-shell, a wayland session and gdm
	# â every check above â while providing no file manager, no portal
	# backend, no keyring and no gvfs. It passed this gate with 192
	# packages against yellowfin:gnome's 576 (tunaos-packages#132).
	#
	# These four are required because without them the desktop is not
	# merely sparse, it is broken in ways a user hits immediately: no way
	# to browse files, Flatpak file dialogs and screenshots fail (portal),
	# saved credentials fail (keyring), removable media and network shares
	# do not mount (gvfs).
	#
	# Deliberately scoped to GNOME. Every one was verified present in
	# yellowfin:gnome and albacore:gnome before being made mandatory â a
	# requirement that has not been checked against a known-good image
	# turns working builds red instead of catching broken ones. Extend to
	# kde/xfce/niri/cosmic the same way: measure a healthy image first.
	require_command nautilus
	# One glob per packaging family â see the measured table above the case.
	# openSUSE (/usr/libexec/gvfs/gvfsd, owned by gvfs-1.60.1 on Tumbleweed)
	# and Arch (/usr/lib/gvfsd) were the two real paths missing: sailfin:gnome
	# installed gvfs, gvfs-backends and gvfs-fuse and still failed this gate.
	# NB Debian does NOT use a multiarch triplet here â measured, it is plain
	# /usr/lib/gvfs/gvfsd (plus /usr/libexec/gvfsd), so no /usr/lib/*/ arm is
	# needed and none is kept.
	require_any_glob \
		'/usr/libexec/gvfsd' \
		'/usr/libexec/gvfs/gvfsd' \
		'/usr/lib/gvfsd' \
		'/usr/lib/gvfs/gvfsd'
	# Portal backend and keyring, measured the same way (table above the case):
	# /usr/libexec on Fedora, EL, Debian, Ubuntu and openSUSE; /usr/lib on Arch.
	# gnome-keyring-daemon is /usr/bin on all five.
	require_any_glob \
		'/usr/libexec/xdg-desktop-portal-gnome' \
		'/usr/lib/xdg-desktop-portal-gnome'
	require_any_glob '/usr/bin/gnome-keyring-daemon'
	# User systemd units: audio (pipewire/wireplumber) user unit definitions.
	require_any_user_unit pipewire wireplumber
	# GNOME Shell extensions assertion: verified presence of system extensions under /usr/share/gnome-shell/extensions.
	if compgen -G "/usr/share/gnome-shell/extensions/*" >/dev/null 2>&1; then
		:
	else
		echo "missing required GNOME Shell extensions under /usr/share/gnome-shell/extensions" >&2
		exit 1
	fi
	# dconf compiled database: every keyfile dir /etc/dconf/db/<name>.d/ must have
	# a compiled /etc/dconf/db/<name>. Iterate instead of hardcoding local/gdm â
	# distros ship their own keyfile dirs (ibus.d on Arch) already compiled by
	# package postinst; hardcoding local/gdm fails those falsely.
	for _dcf_dir in /etc/dconf/db/*.d; do
		[[ -d "$_dcf_dir" ]] || continue
		if compgen -G "$_dcf_dir/*" >/dev/null 2>&1; then
			_dcf_name="${_dcf_dir%.d}"
			_dcf_name="${_dcf_name##*/}"
			if [[ ! -s "/etc/dconf/db/${_dcf_name}" ]]; then
				echo "missing compiled dconf database: keyfiles in ${_dcf_dir} but /etc/dconf/db/${_dcf_name} is missing or empty (run dconf update)" >&2
				exit 1
			fi
		fi
	done
	;;
kde)
	experience="ublue-os/aurora"
	require_command plasmashell
	require_glob '/usr/share/wayland-sessions/*plasma*.desktop'
	# KDE 6.5+ renames SDDM to plasmalogin; both are in the wild.
	require_any_unit sddm plasmalogin
	# A Plasma session is not a usable desktop on its own. sailfin:kde
	# shipped plasmashell, kwin6 and systemsettings with NO file manager and
	# NO terminal, because patterns-kde-kde resolves to the shell only.
	# dolphin and konsole are the two the user cannot work without, and they
	# are the only KDE applications listed EXPLICITLY in every manifest
	# section that builds KDE â kde.yaml apt/fedora/el10/zypper/emerge plus
	# kde-arch.yaml and kde-debian.yaml â so requiring them cannot redden a
	# variant that is building correctly. Deliberately NOT asserted:
	# xdg-desktop-portal-kde (absent from the emerge list, and guppy builds
	# KDE) and plasma6-nm/kwallet (nowhere explicit; they arrive as
	# dependencies, which differ per distro).
	require_command dolphin
	require_command konsole
	dm_pattern='^(sddm|plasmalogin)\.service$'
	;;
niri)
	experience="zirconium-dev/zirconium"
	require_command niri
	require_glob '/usr/share/wayland-sessions/*niri*.desktop'
	require_unit greetd
	# niri is only a compositor: it has no portal, no secret store and no
	# shell of its own. sailfin:niri shipped `niri` and `greetd` and nothing
	# else. The shell itself cannot be asserted â Fedora and EL10 use DMS
	# (quickshell) while openSUSE uses the wlroots stack (waybar/fuzzel),
	# because quickshell and dms are not built for the opensuse-tumbleweed
	# target yet: it IS declared in manifests/package-factory.yaml, but has no
	# cells in the package build gate (tunaos-packages#139). Revisit when it
	# does. The portal and the keyring ARE common:
	# both are explicit in every niri section that builds (fedora, el10,
	# zypper, pacman). Accept the gtk backend alongside gnome â a variant may
	# reasonably ship only the former.
	require_any_glob \
		'/usr/libexec/xdg-desktop-portal-gnome' '/usr/lib/xdg-desktop-portal-gnome' \
		'/usr/libexec/xdg-desktop-portal-gtk' '/usr/lib/xdg-desktop-portal-gtk'
	require_any_glob '/usr/bin/gnome-keyring-daemon'
	dm_pattern='^greetd\.service$'
	;;
cosmic)
	experience="tunaos/cosmic"
	require_command cosmic-comp
	require_glob '/usr/share/wayland-sessions/*cosmic*.desktop'
	require_unit greetd
	# Extended per tunaOS#916's own checklist item, with the same discipline
	# GNOME/KDE/XFCE were held to: measure the manifest first, then require.
	#
	# cosmic-files and xdg-desktop-portal-cosmic are explicit, non-optional
	# entries in manifests/desktops/cosmic.yaml's apt, fedora and zypper
	# sections, and in cosmic-arch.yaml's pacman section â the same bar
	# dolphin/konsole (kde) and thunar (xfce) were required on ("explicit in
	# every manifest section that builds"). Without a file manager COSMIC is
	# not merely sparse, it is unusable the same way sailfin:gnome was
	# (tunaos-packages#132, the issue that started this whole contract).
	#
	# el10 (yellowfin/albacore/skipjack/redfin) is deliberately excluded:
	# there both packages come from the yselkowitz/cosmic-epel COPR
	# (cosmic.yaml's el10.copr section), and install-desktop.sh installs
	# every copr block with `|| true` (the exact "COPR packages" step,
	# distinct from the regular `dnf_retry -y install` used for fedora/apt/
	# zypper/pacman, which has no such fallback) â a flaky COPR there can
	# legitimately produce a build that has always shipped correctly. The
	# condition below reproduces install-desktop.sh's own _TD_OS="el10"
	# fallback exactly (dnf-based, not Fedora, not Hummingbird) rather than
	# re-deriving it from a distro-name enumeration that could drift out of
	# sync with the real branching logic.
	#
	# Binary path for cosmic-files confirmed live (mdapi.fedoraproject.org
	# rawhide file list, 2026-08-08): /usr/bin/cosmic-files, so a plain PATH
	# check is correct. xdg-desktop-portal-cosmic confirmed the same way:
	# /usr/libexec/xdg-desktop-portal-cosmic on Fedora â matching this same
	# file's already-twice-measured portal convention (libexec on Fedora/EL/
	# Debian/Ubuntu/openSUSE, lib on Arch, see the table above the case
	# statement), which xdg-desktop-portal-cosmic packaging follows for the
	# same reason its sibling backends (-gnome, -gtk) do: all three build
	# from the same upstream xdg-desktop-portal libexecdir convention per
	# distro. Not independently re-measured on Ubuntu/openSUSE/Arch in this
	# change (no zstd tooling available to read their repodata here) â recorded
	# so the next person knows which half of this is live-verified and which
	# is carried over from an already-established pattern, same as this
	# file's own stated rule asks for.
	if [[ "${PKG_MGR:-}" == "dnf" && "${IS_FEDORA:-false}" != true && "${IS_HUMMINGBIRD:-false}" != true ]]; then
		echo "info: skipping cosmic-files/xdg-desktop-portal-cosmic on the el10 family â cosmic.yaml sources them from a best-effort COPR here (tunaOS#916)"
	else
		require_command cosmic-files
		require_any_glob \
			'/usr/libexec/xdg-desktop-portal-cosmic' \
			'/usr/lib/xdg-desktop-portal-cosmic'
	fi
	# cosmic-greeter.service is accepted alongside greetd.service because it is
	# greetd: `ExecStart=greetd --config /etc/greetd/cosmic-greeter.toml`, with
	# `Provides: x-display-manager` and `Pre-Depends: greetd` on the deb. On
	# Ubuntu its postinst claims the display-manager.service alias, so
	# `systemctl show -P Id display-manager.service` reports cosmic-greeter
	# there while Fedora/EL10 report greetd. Pinning only greetd would fail
	# grouper:cosmic on a correctly-wired COSMIC login screen.
	dm_pattern='^(greetd|cosmic-greeter)\.service$'
	;;
xfce)
	experience="tunaos/xfce"
	require_command xfce4-session
	require_any_glob '/usr/share/xsessions/*xfce*.desktop' '/usr/share/wayland-sessions/*xfce*.desktop'
	require_any_unit gdm gdm3 lightdm greetd
	# sailfin:xfce shipped a session with no file manager thumbnails, no
	# gvfs and NO portal at all â Flatpak file dialogs were simply broken.
	# thunar and xdg-desktop-portal-gtk are explicit in every xfce section
	# that builds (fedora, el10, apt, zypper, pacman). NOT asserted:
	# xfce4-terminal â Debian gets it via the `xfce4` metapackage's
	# Recommends, which an apt build may legitimately not install.
	require_command thunar
	require_any_glob \
		'/usr/libexec/xdg-desktop-portal-gtk' '/usr/lib/xdg-desktop-portal-gtk'

	# xfwl4 reads xfwm4's THEME DATA and panics without it â not a warning, a
	# hard abort before the session exists:
	#
	#   xfwl4::backend::udev: Using renderD128 as primary GPU
	#   smithay::wayland::socket: Created new socket name="wayland-1"
	#   thread 'main' panicked at src/core/state.rs:260:74:
	#   Failed to load initial config: Failed to find theme named Default
	#
	# yellowfin:xfce in installer-smoke run 31183217981 booted to a console of
	# that backtrace: no desktop, no installer, nothing to screenshot. It reads
	# like the GPU-less runner limitation and is not â the same log line says a
	# render node WAS found.
	#
	# xfce.sh already pulls xfwm4 for this reason, but through
	# install_available, which is best-effort by design and skips silently when
	# the package does not resolve on a base. So the theme data can be absent
	# with nothing in the build log to say so, and the first symptom is a
	# compositor panic on a user's machine. Assert it here instead: an image
	# whose compositor cannot start is not a shippable image.
	#
	# Guarded on xfwl4 being present because the X11 branch (xfwm4 as the WM on
	# bases without the Wayland stack) pulls the same package as a dependency
	# and would never reach this state.
	if command -v xfwl4 >/dev/null 2>&1; then
		require_any_glob \
			'/usr/share/themes/Default/xfwm4/themerc' \
			'/usr/share/themes/Default/xfwm4'
	fi

	xfce_greetd_greeter_contract
	dm_pattern='^(gdm|gdm3|lightdm|greetd)\.service$'
	;;
pantheon)
	# gurnard only: Pantheon comes exclusively from ppa:elementary-os/stable
	# (manifests/desktops/pantheon.yaml). Until 2026-08-07 this case did not
	# exist, so gurnard:pantheon sailed through the LUKS gates with
	# desktop_contract=absent â a green cell whose desktop was never proven
	# (run 31074188677, found by the full-matrix contract audit). The asserts
	# mirror what the manifest actually installs, nothing invented: `gala` is
	# the compositor package and its binary keeps that name, the session
	# entry ships as pantheon.desktop, and the manifest pins
	# display_manager: lightdm.
	experience="tunaos/pantheon"
	require_command gala
	# Session entries measured from the PPA deb itself (pantheon-xsession-
	# settings 8.1.0+r419, dpkg -c, 2026-08-07): xsessions/pantheon.desktop
	# and wayland-sessions/pantheon-wayland.desktop. The first run of this
	# contract (31187758113) failed here and the failure was REAL: no package
	# in the manifest shipped any session entry at all â the greeter had
	# nothing to launch. pantheon-xsession-settings is that package; the
	# manifest now installs it.
	require_any_glob '/usr/share/xsessions/pantheon*.desktop' \
		'/usr/share/wayland-sessions/pantheon*.desktop'
	require_any_unit lightdm
	dm_pattern='^lightdm\.service$'
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
	# wants â the target cannot become active until this script exits, so
	# that check self-deadlocks into a guaranteed failure. Assert the boot
	# *default* instead; liveness comes from the display-manager check below.
	if [[ "$(systemctl get-default 2>/dev/null)" != graphical.target ]]; then
		report_fail default_target_not_graphical
	fi
	# Check the display-manager.service alias (every DM registers it) and
	# verify its Id resolves to a DM this desktop's contract allows â robust
	# to per-distro unit names (gdm vs gdm3, lightdm vs greetd for xfce).
	dm_id=$(systemctl show -P Id display-manager.service 2>/dev/null || true)
	if ! systemctl is-active --quiet display-manager.service 2>/dev/null; then
		report_fail "dm_inactive desktop=$desktop"
		# `dm_inactive` alone is not a diagnosis, and the reason why is
		# structural: the DM logs to the journal, while the E2E gate can only
		# read the serial console, so the actual error is invisible and every
		# hypothesis costs a full image build. Ship the evidence with the
		# failure â this is how a greetd exiting instantly on a missing
		# greeter account looked identical to one whose greeter could not
		# render.
		{
			systemctl show \
				--property=Id,ActiveState,SubState,Result,ExecMainStatus,NRestarts \
				display-manager.service
			[[ -n "$dm_id" ]] && journalctl -b --no-pager -n 25 -u "$dm_id"
		} 2>&1 | sed 's/^/dm_diag: /' | tee /dev/ttyS0 2>/dev/null || true
	elif [[ ! "$dm_id" =~ $dm_pattern ]]; then
		report_fail "dm_mismatch dm=${dm_id:-unknown} expected=${dm_pattern}"
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
	# ââ Static unit-graph validation (pattern from secureblue's
	# validate_systemd_unit_files.sh) ââ catches unit typos, missing
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

	# ââ Launcher validation (pattern from ublue-os/aurora's 20-tests.sh) ââ
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

	# ââ Codec baseline ââ
	# "Codecs installed" was promised on every family and verified on none â
	# the EL10 x86_64_v2 leg shipped ffmpeg-free only (no H.264/H.265 at
	# all) and marlin shipped gst-plugins-ugly without gst-libav (x264
	# ENcoder present, no mainstream DEcoder), and both were green. Two
	# file-level proofs, both cheap and network-free:
	#
	# 1. The GStreamer libav plugin exists â the piece that lets totem,
	#    thumbnailers and WebKit decode through libavcodec. One measured
	#    path per packaging family (repo rule: no unmeasured globs):
	#      rpm/openSUSE/Gentoo  /usr/lib64/gstreamer-1.0/libgstlibav.so
	#      Arch                 /usr/lib/gstreamer-1.0/libgstlibav.so
	#      Debian/Ubuntu        /usr/lib/<triplet>/gstreamer-1.0/libgstlibav.so
	#      (the apt path MEASURED on ubuntu:noble â gstreamer1.0-libav ships
	#      /usr/lib/x86_64-linux-gnu/gstreamer-1.0/libgstlibav.so)
	# 2. `ffmpeg -decoders` actually lists h264 â the plugin above routes
	#    into libavcodec, so a free-codec libavcodec (the exact v2 failure)
	#    is caught here even though the plugin file exists.
	require_any_glob \
		'/usr/lib64/gstreamer-1.0/libgstlibav.so' \
		'/usr/lib/gstreamer-1.0/libgstlibav.so' \
		'/usr/lib/*/gstreamer-1.0/libgstlibav.so'
	require_command ffmpeg
	if command -v ffmpeg >/dev/null 2>&1; then
		# NEVER pipe ffmpeg straight into `grep -q` here. grep -q exits at the
		# first match, ffmpeg is still writing its ~30 KB decoder list, gets
		# SIGPIPE, exits 141 â and under this script's `set -o pipefail` the
		# pipeline reports failure WITH the decoder present. That is not a
		# race in practice: measured on ubuntu:noble (ffmpeg 6.1.1, h264
		# decoder confirmed in the output), the piped form returned 141 on
		# five out of five runs and failed gurnard:pantheon's proof build
		# (run 31196812732) with a message blaming a "crippled libavcodec"
		# the image did not have. Capture first, then grep the variable â
		# and keep "ffmpeg would not run" distinct from "ffmpeg runs but
		# cannot decode", because their fixes live in different places
		# (packaging deps vs codec sourcing).
		# Both failure branches dump the evidence that names the cause,
		# because this check fired on guppy:xfce (run 31201546516) with a
		# freshly source-built ffmpeg 8.1.2 whose USE line showed x264 â
		# a build where the native h264 decoder should be unconditional â
		# while the same check passes inside the July guppy:gnome image
		# and against Alpine's 8.1.2. Three container reproductions of the
		# tooling stage could not replicate it (portage tree drift), so
		# the next failing run must answer for itself: WHICH ffmpeg ran,
		# what its configure line disabled, what it printed to stderr
		# (previously discarded), and what the decoder list actually held.
		_ffmpeg_diag() {
			{
				echo "codec_diag: ffmpeg=$(command -v ffmpeg)"
				ffmpeg -version 2>&1 | head -2 | sed 's/^/codec_diag: /'
				ffmpeg -version 2>&1 | tr ' ' '\n' | grep -- '--disable-\(everything\|decoders\|decoder=[a-z0-9_]*\)' | sed 's/^/codec_diag: configure /'
				echo "codec_diag: decoders_stdout_bytes=${#_ffmpeg_decoders}"
				echo "codec_diag: decoders_stderr: ${_ffmpeg_stderr:-<empty>}"
				grep -i 'h26' <<<"$_ffmpeg_decoders" | head -5 | sed 's/^/codec_diag: h26x /'
			} >&2 || true
		}
		_ffmpeg_decoders=""
		_ffmpeg_stderr=""
		_ffmpeg_rc=0
		_ffmpeg_stderr_file="$(mktemp)"
		_ffmpeg_decoders="$(ffmpeg -hide_banner -decoders 2>"$_ffmpeg_stderr_file")" || _ffmpeg_rc=$?
		_ffmpeg_stderr="$(head -c 2048 "$_ffmpeg_stderr_file")"
		rm -f "$_ffmpeg_stderr_file"
		if ((_ffmpeg_rc != 0)); then
			echo "ffmpeg is installed but would not run (broken dependencies?) â cannot verify codecs" >&2
			_ffmpeg_diag
			if [[ "${IS_HUMMINGBIRD:-false}" != "true" ]]; then
				exit 1
			fi
		elif ! grep -q ' h264 ' <<<"$_ffmpeg_decoders"; then
			echo "ffmpeg cannot decode h264 â a free/crippled libavcodec is installed" >&2
			_ffmpeg_diag
			if [[ "${IS_HUMMINGBIRD:-false}" != "true" ]]; then
				exit 1
			fi
		fi
	fi

	# ââ KDE version-skew guard (pattern from ublue-os/aurora's 20-tests.sh) ââ
	# Mid-compose repo skew can ship kwin/kscreen from a newer Plasma than
	# plasma-desktop; the session then crashes at login while every package
	# transaction "succeeded". Version equality across installed Plasma core
	# packages is a hard invariant on rpm variants â fail the build on skew.
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

	# ââ Flatpak baseline (store + browser + a remote that can serve them) ââ
	# Asserts exactly what the build now lays down, nothing aspirational:
	# tuna-flatpak-remote.sh bakes the Flathub remote on every base, and
	# flatpak-preinstall.sh declares the curated set (io.github.kolunmi.Bazaar
	# as the store, org.mozilla.firefox as the browser â Bluefin's choices)
	# and enables flatpak-preinstall.service where the base's flatpak ships
	# it. Guarded on flatpak existing so a hypothetical flatpak-less image is
	# out of scope rather than red. The per-app grep list below is kept in
	# lockstep with flatpak-preinstall.sh by
	# tests/bats/test_build_scripts_remaining.bats â change both together.
	if command -v flatpak >/dev/null 2>&1; then
		require_glob '/etc/flatpak/remotes.d/flathub.flatpakrepo'
		require_glob '/usr/share/flatpak/preinstall.d/*.preinstall'
		for _fp_app in io.github.kolunmi.Bazaar org.mozilla.firefox; do
			if ! grep -rqs "^\[Flatpak Preinstall ${_fp_app}\]" /usr/share/flatpak/preinstall.d; then
				echo "missing flatpak preinstall declaration: ${_fp_app}" >&2
				if [[ "${IS_HUMMINGBIRD:-false}" != "true" ]]; then
					exit 1
				fi
			fi
		done
		# Where the unit exists, declarations without the service are inert â
		# that combination shipped: preinstall files with nothing to run them.
		if [[ -f /usr/lib/systemd/system/flatpak-preinstall.service ]]; then
			if ! systemctl is-enabled flatpak-preinstall.service >/dev/null 2>&1; then
				echo "flatpak-preinstall.service is shipped but not enabled â the declared flatpaks would never install" >&2
				if [[ "${IS_HUMMINGBIRD:-false}" != "true" ]]; then
					exit 1
				fi
			fi
		else
			echo "info: this base's flatpak ships no flatpak-preinstall.service; declarations are documentation until it does"
		fi
	fi

	# ââ Branding & Asset Contract ââ
	# Wallpapers: shipping only upstream artwork means a user sees upstream background on login.
	if ! compgen -G "/usr/share/backgrounds/tunaos*" >/dev/null &&
		! compgen -G "/usr/share/backgrounds/*/tunaos*" >/dev/null &&
		! compgen -G "/usr/share/backgrounds/bluefin*" >/dev/null; then
		echo "::warning::missing required path: /usr/share/backgrounds/tunaos* (branding wallpaper)" >&2
		if [[ "${WALLPAPER_CHECK_FATAL:-0}" -eq 1 ]]; then
			exit 1
		fi
	fi

	# dconf compiled database: every keyfile dir /etc/dconf/db/<name>.d/ must have
	# a compiled /etc/dconf/db/<name>. Iterate instead of hardcoding local/gdm â
	# distros ship their own keyfile dirs (ibus.d on Arch) already compiled by
	# package postinst; hardcoding local/gdm fails those falsely.
	for _dcf_dir in /etc/dconf/db/*.d; do
		[[ -d "$_dcf_dir" ]] || continue
		if compgen -G "$_dcf_dir/*" >/dev/null 2>&1; then
			_dcf_name="${_dcf_dir%.d}"
			_dcf_name="${_dcf_name##*/}"
			if [[ ! -s "/etc/dconf/db/${_dcf_name}" ]]; then
				echo "missing compiled dconf database: keyfiles in ${_dcf_dir} but /etc/dconf/db/${_dcf_name} is missing or empty (run dconf update)" >&2
				if [[ "${IS_HUMMINGBIRD:-false}" != "true" ]]; then
					exit 1
				fi
			fi
		fi
	done

	install -d /usr/share/tunaos/experience-contracts
	printf 'desktop=%s\nexperience=%s\nvalidated_at_build=true\n' "$desktop" "$experience" \
		>"/usr/share/tunaos/experience-contracts/${desktop}"
	echo "desktop experience contract passed: $desktop ($experience)"
fi
