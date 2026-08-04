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

# PORTAL/KEYRING/GVFS PATHS — measured, one container per packaging family.
# Never add a glob you have not seen resolve on a real distro: an invented
# pattern that matches nothing turns a working desktop red, which is exactly
# what '/usr/lib/*/gvfs/gvfsd' did to sailfin and marlin.
#
#   family          gvfsd                          portal-gnome / portal-gtk
#   Fedora / EL     /usr/libexec/gvfsd             /usr/libexec/...
#   Debian/Ubuntu   /usr/libexec/gvfsd AND         /usr/libexec/...
#                   /usr/lib/gvfs/gvfsd
#                   (package is gvfs-daemons, NOT gvfs — plain gvfs ships
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
	# and gnome-shell IS installed — so the old glob reported a working GNOME
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
	# — every check above — while providing no file manager, no portal
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
	# yellowfin:gnome and albacore:gnome before being made mandatory — a
	# requirement that has not been checked against a known-good image
	# turns working builds red instead of catching broken ones. Extend to
	# kde/xfce/niri/cosmic the same way: measure a healthy image first.
	require_command nautilus
	# One glob per packaging family — see the measured table above the case.
	# openSUSE (/usr/libexec/gvfs/gvfsd, owned by gvfs-1.60.1 on Tumbleweed)
	# and Arch (/usr/lib/gvfsd) were the two real paths missing: sailfin:gnome
	# installed gvfs, gvfs-backends and gvfs-fuse and still failed this gate.
	# NB Debian does NOT use a multiarch triplet here — measured, it is plain
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
	# dconf compiled database: keyfiles in /etc/dconf/db/*.d/ must be compiled into binary dconf DB.
	# dconf-update.service handles this at first boot; during build, dconf update may
	# not work on all distros (Arch lacks the expected dconf profile). Warn but don't block.
	if compgen -G "/etc/dconf/db/*.d/*" >/dev/null 2>&1; then
		if [[ ! -s /etc/dconf/db/local && ! -s /etc/dconf/db/gdm ]]; then
			echo "warning: dconf keyfiles present but compiled database missing (will be compiled at first boot by dconf-update.service)" >&2
		fi
	fi
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
	# section that builds KDE — kde.yaml apt/fedora/el10/zypper/emerge plus
	# kde-arch.yaml and kde-debian.yaml — so requiring them cannot redden a
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
	# else. The shell itself cannot be asserted — Fedora and EL10 use DMS
	# (quickshell) while openSUSE uses the wlroots stack (waybar/fuzzel),
	# because quickshell and dms are not built for the opensuse-tumbleweed
	# target yet: it IS declared in manifests/package-factory.yaml, but has no
	# cells in the package build gate (tunaos-packages#139). Revisit when it
	# does. The portal and the keyring ARE common:
	# both are explicit in every niri section that builds (fedora, el10,
	# zypper, pacman). Accept the gtk backend alongside gnome — a variant may
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
	# NOT extended. cosmic-files and xdg-desktop-portal-cosmic look like the
	# obvious requirements, but on el10 they are installed from a COPR, and
	# copr installs are best-effort — a flaky COPR would turn a requirement
	# into a hard build failure on a variant that has always built. Nor is
	# either path measured on any published cosmic image yet. Measure
	# bonito:cosmic (fedora) and flounder:cosmic (apt) first, then decide.
	dm_pattern='^greetd\.service$'
	;;
xfce)
	experience="tunaos/xfce"
	require_command xfce4-session
	require_any_glob '/usr/share/xsessions/*xfce*.desktop' '/usr/share/wayland-sessions/*xfce*.desktop'
	require_any_unit gdm gdm3 lightdm greetd
	# sailfin:xfce shipped a session with no file manager thumbnails, no
	# gvfs and NO portal at all — Flatpak file dialogs were simply broken.
	# thunar and xdg-desktop-portal-gtk are explicit in every xfce section
	# that builds (fedora, el10, apt, zypper, pacman). NOT asserted:
	# xfce4-terminal — Debian gets it via the `xfce4` metapackage's
	# Recommends, which an apt build may legitimately not install.
	require_command thunar
	require_any_glob \
		'/usr/libexec/xdg-desktop-portal-gtk' '/usr/lib/xdg-desktop-portal-gtk'
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
	dm_id=$(systemctl show -P Id display-manager.service 2>/dev/null || true)
	if ! systemctl is-active --quiet display-manager.service 2>/dev/null; then
		report_fail "dm_inactive desktop=$desktop"
		# `dm_inactive` alone is not a diagnosis, and the reason why is
		# structural: the DM logs to the journal, while the E2E gate can only
		# read the serial console, so the actual error is invisible and every
		# hypothesis costs a full image build. Ship the evidence with the
		# failure — this is how a greetd exiting instantly on a missing
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

	# ── Branding & Asset Contract ──
	# Wallpapers: shipping only upstream artwork means a user sees upstream background on login.
	if ! compgen -G "/usr/share/backgrounds/tunaos*" >/dev/null &&
		! compgen -G "/usr/share/backgrounds/*/tunaos*" >/dev/null &&
		! compgen -G "/usr/share/backgrounds/bluefin*" >/dev/null; then
		echo "missing required path: /usr/share/backgrounds/tunaos* (branding wallpaper)" >&2
		if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then exit 0; fi
		exit 1
	fi

	# dconf compiled database: desktop branding keyfiles in /etc/dconf/db/*.d must be compiled.
	# dconf-update.service handles this at first boot. dconf update may fail
	# during build on some distros (Arch lacks expected dconf profiles). Warn only.
	if compgen -G "/etc/dconf/db/*.d/*" >/dev/null 2>&1; then
		if [[ ! -s /etc/dconf/db/local && ! -s /etc/dconf/db/gdm ]]; then
			echo "warning: dconf keyfiles present but compiled database missing (will be compiled at first boot by dconf-update.service)" >&2
		fi
	fi

	install -d /usr/share/tunaos/experience-contracts
	printf 'desktop=%s\nexperience=%s\nvalidated_at_build=true\n' "$desktop" "$experience" \
		>"/usr/share/tunaos/experience-contracts/${desktop}"
	echo "desktop experience contract passed: $desktop ($experience)"
fi
