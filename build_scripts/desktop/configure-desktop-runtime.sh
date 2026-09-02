#!/usr/bin/env bash

set -euo pipefail

desktop="${1:?usage: configure-desktop-runtime.sh <gnome|kde|niri|cosmic|xfce|pantheon>}"

# Desktop packages are installed in later Containerfile stages than the base
# service setup. Enable their display manager only after its unit exists.
case "$desktop" in
gnome) dm=gdm ;;
kde)
	# Plasma 6.6 renamed SDDM to PlasmaLogin. On EL10, plasma-login-manager
	# arrives as a plasma-group dependency and claims the
	# display-manager.service alias before our explicit `sddm` install can,
	# so prefer it wherever it exists; Fedora/Debian/Ubuntu/Arch still ship
	# sddm. `systemctl enable` below is NOT `|| true` -- enabling the unit
	# the image does not have would fail here rather than at boot.
	if systemctl list-unit-files plasmalogin.service --no-legend 2>/dev/null | grep -q '^plasmalogin.service'; then
		dm=plasmalogin
	else
		dm=sddm
	fi
	;;
niri) dm=greetd ;;
cosmic)
	# Same shape as the kde case above: a package can claim the
	# display-manager.service alias before we get here, and `systemctl
	# enable` on a different DM then hard-fails rather than winning.
	#
	# The PPA's cosmic-greeter deb enables cosmic-greeter.service and points
	# display-manager.service at it in its postinst, so the greetd line blew
	# up the whole grouper:cosmic build:
	#
	#   Failed to enable unit: File '/etc/systemd/system/display-manager.service'
	#   already exists and is a symlink to /lib/systemd/system/cosmic-greeter.service
	#
	# (LUKS run 31135761136.) Deferring to the claim is also right on the
	# merits — cosmic-greeter IS COSMIC's greeter, and it is already enabled
	# at this point.
	#
	# This tests the CLAIM, not the package, which is what makes it correct
	# on every base rather than just the one it was written for.
	#
	# An earlier version of this comment claimed EL10 leaves the alias alone,
	# inferring it from `systemctl enable greetd` succeeding there. That
	# inference was WRONG, and the artifacts say so: albacore:cosmic on head
	# c277780f — before any of this — already reported
	#
	#   # display manager: cosmic-greeter.service
	#   reason=dm_mismatch dm=cosmic-greeter.service
	#
	# EL10's COPR cosmic-greeter claims the alias exactly like the deb does.
	# greetd enables cleanly there for a different reason: Fedora/EL ship
	# greetd.service with `[Install] WantedBy=graphical.target` and no Alias=,
	# while Debian/Ubuntu ship `Alias=display-manager.service` and no
	# WantedBy=. No alias, no conflict — so the EL10 build SUCCEEDS and ships
	# both units, which is worse than failing: greetd and cosmic-greeter both
	# run `greetd` on vt1 with Restart=always, greetd takes the terminal
	# first, and cosmic-greeter crash-loops on
	#
	#   unable to start greeter: terminal: unable to take controlling
	#   terminal: EPERM: Operation not permitted
	#
	# (skipjack:cosmic, run 31136849989 — a cell the board counts GREEN,
	# because the desktop contract that catches it is fatal=0. albacore:cosmic
	# fails the same contract. skipjack:niri passes it on the identical base,
	# so the check works and this is COSMIC-specific.)
	#
	# Keying off the symlink handles that case too: on EL10 the symlink is
	# already cosmic-greeter, so this picks cosmic-greeter and the sibling
	# guard in install-desktop.sh stops force-linking greetd beside it.
	#
	# NOT `systemctl enable --force`: the kde comment above records why
	# forcing the alias is the wrong instrument (tunaOS#824).
	if [[ "$(readlink -f /etc/systemd/system/display-manager.service 2>/dev/null)" == *cosmic-greeter.service ]]; then
		dm=cosmic-greeter
	else
		dm=greetd
	fi
	;;
xfce)
	# Debian-family packaging records the DM debconf chose in
	# /etc/X11/default-display-manager, and BOTH gdm3 and lightdm consult it
	# at startup — each refuses to run when the file names the other. That
	# turned "prefer lightdm when its unit exists" into a broken desktop on
	# grouper:xfce (run 31181743606): the manifest installs gdm3, Ubuntu's
	# xfce4 metapackage pulls lightdm in via Recommends, this branch enabled
	# the lightdm it found, and the installed system's serial shows lightdm
	# crash-looping six times against default-display-manager=gdm3 while
	# gdm3 — the DM debconf actually configured — sat unenabled. The
	# contract service correctly reported DEPEND-failed, so the cell read
	# desktop_contract=absent while the LUKS gates stayed green.
	#
	# Defer to the file: it is the apt-family equivalent of the
	# display-manager.service alias claim the cosmic branch above defers to
	# — the distro's packaging has already decided, and enabling anything
	# else just loses a fight at boot. The unit-existence fallbacks remain
	# for bases that never write the file.
	if [[ -r /etc/X11/default-display-manager ]]; then
		dm="$(basename "$(cat /etc/X11/default-display-manager)")"
	elif systemctl list-unit-files lightdm.service --no-legend 2>/dev/null | grep -q '^lightdm.service'; then
		dm=lightdm
	else
		dm=greetd
	fi
	;;
pantheon)
	# manifests/desktops/pantheon.yaml pins display_manager: lightdm and the
	# elementary PPA's greeter (io.elementary.greeter) is a LightDM greeter.
	# Until 2026-08-07 pantheon fell through to the `*) exit 0` below: no DM
	# enable, no graphical.target default, and — the part the matrix could
	# not see — no tunaos-desktop-contract.service, so gurnard:pantheon was
	# green with desktop_contract=absent (run 31074188677). Landing here also
	# puts pantheon in the contract family case further down.
	dm=lightdm
	;;
*) exit 0 ;;
esac

# Still a hard failure — an image with no display manager is worse than a
# failed build, which is why none of the branches above use `|| true`. But say
# what happened before dying. systemd's own message names a FILE:
#
#   Failed to enable unit: File '/etc/systemd/system/display-manager.service'
#   already exists and is a symlink to /lib/systemd/system/cosmic-greeter.service
#
# which does not mention the desktop, the package that claimed it, or what to
# do. Reading that cost three separate 20-minute grouper:cosmic builds
# (LUKS run 31135761136). The two cases have opposite fixes, so name which one
# this is.
if ! systemctl enable "${dm}.service"; then
	# -L first: `readlink -f` prints the canonical path even when the file
	# does not exist, so testing its output for emptiness reports "claimed by
	# display-manager.service" on a system where nothing claimed anything —
	# the opposite diagnosis, with the opposite fix. Caught by the
	# unclaimed-alias case below before this shipped.
	_dm_claim=""
	if [[ -L /etc/systemd/system/display-manager.service ]]; then
		_dm_claim="$(readlink -f /etc/systemd/system/display-manager.service 2>/dev/null || true)"
	fi
	echo "ERROR: cannot enable ${dm}.service as ${desktop}'s display manager." >&2
	if [[ -n "${_dm_claim}" && "${_dm_claim##*/}" != "${dm}.service" ]]; then
		echo "       display-manager.service is already claimed by ${_dm_claim##*/}," >&2
		echo "       set by that package's post-install before this script ran." >&2
		echo "       Defer to it (see how the kde and cosmic branches above pick" >&2
		echo "       a DM) rather than forcing the alias — forcing it repoints" >&2
		echo "       every image that shares this path (tunaOS#824)." >&2
	else
		echo "       Nothing else claims the alias, so ${dm}.service is most" >&2
		echo "       likely not installed. Check that the ${desktop} manifest" >&2
		echo "       actually pulls in the package providing it." >&2
	fi
	exit 1
fi
systemctl set-default graphical.target

# Debian's lightdm expects /var state that a bootc install never has. The
# package ships /var/cache/lightdm, /var/lib/lightdm-data and
# /var/log/lightdm as dpkg directories and creates /var/lib/lightdm in its
# postinst (adduser --home) — and ships NO tmpfiles.d entries at all
# (measured on ubuntu:noble, dpkg -L lightdm; gdm3 self-creates its dirs at
# runtime, which is why grouper:gnome never hit this). ostree/bootc installs
# start with a fresh machine-local /var, so every one of those directories
# is missing on first boot; lightdm dies, Restart=always loops it, and both
# proof cells (gurnard:pantheon 31204811851, grouper:xfce 31204818233)
# showed six FAILED lines and desktop_contract=absent. Give the dirs the
# mechanism the package forgot: tmpfiles.d, ownership and modes as measured
# from the installed package.
if systemctl list-unit-files lightdm.service --no-legend 2>/dev/null | grep -q '^lightdm.service'; then
	cat >/usr/lib/tmpfiles.d/tunaos-lightdm-state.conf <<'EOF'
# lightdm ships these as dpkg dirs / postinst artifacts, with no tmpfiles.d
# of its own — on a bootc system machine-local /var starts empty and the DM
# crash-loops without them. Ownership/modes measured on ubuntu:noble.
d /var/lib/lightdm 0750 lightdm lightdm -
d /var/lib/lightdm-data 0755 lightdm lightdm -
d /var/cache/lightdm 0755 root root -
d /var/log/lightdm 0755 root root -
EOF
	echo "configure-desktop-runtime: wrote tmpfiles.d for lightdm /var state (bootc fresh-/var)"
fi

# Every desktop family ships an explicit runtime contract plus the
# snosi-derived installed-system TAP checks (harvested from the serial
# console by scripts/iso-e2e.sh; the checks ExecStart is non-fatal).
case "$desktop" in
gnome | kde | niri | cosmic | xfce | pantheon)
	# ── Flatpak baseline, BEFORE the contract that asserts it ─────────────
	# The baseline (Flathub remote + curated preinstall declarations +
	# preinstall service) normally arrives through install-desktop.sh's
	# post_install hooks — but not every desktop stage is manifest-driven.
	# Containerfile.ubuntu's niri and xfce stages run their per-DE scripts
	# (niri.sh/xfce.sh) plus THIS script and never touch install-desktop.sh,
	# so grouper:xfce failed its own contract at build time:
	#
	#   missing required path: /etc/flatpak/remotes.d/flathub.flatpakrepo
	#   (run 31192228329)
	#
	# The assert was right — the image genuinely lacked the remote. Laying
	# the baseline down HERE, inside the same block that runs the contract,
	# makes that drift impossible: any desktop path that verifies the
	# experience has just installed the baseline it verifies, and a stage
	# that skips both this script and install-desktop.sh is refused by
	# tests/bats/test_containerfile_context_scripts.bats. Both scripts are
	# idempotent (the remote fetch is guarded by the baked file, the
	# preinstall writer dedups, the service enable re-runs clean), so the
	# manifest-driven stages that already ran them lose nothing.
	export DESKTOP_FLAVOR="$desktop"
	# shellcheck source=/dev/null
	source /run/context/build_scripts/desktop/tuna-flatpak-remote.sh
	# shellcheck source=/dev/null
	source /run/context/build_scripts/desktop/flatpak-preinstall.sh

	# Compile dconf databases before verify checks — desktop stages lay down
	# keyfiles after the base stage's dconf update, so recompile here.
	if command -v dconf &>/dev/null && compgen -G "/etc/dconf/db/*.d/*" >/dev/null 2>&1; then
		dconf update || true
	fi

	/run/context/build_scripts/checks/verify-desktop-experience.sh "$desktop"
	install -Dm0755 /run/context/build_scripts/checks/verify-desktop-experience.sh \
		/usr/libexec/tunaos/verify-desktop-experience
	install -Dm0755 /run/context/build_scripts/checks/e2e-runtime-checks.sh \
		/usr/libexec/tunaos/e2e-runtime-checks

	# Branding contract — common to every desktop, plus per-desktop surfaces.
	# The branding scripts take the VARIANT (fish codename), not the desktop.
	/run/context/build_scripts/checks/verify-branding.sh "${IMAGE_NAME:-$desktop}"
	install -Dm0755 /run/context/build_scripts/checks/verify-branding.sh \
		/usr/libexec/tunaos/verify-branding
	BRANDING_EXTRA=""
	case "$desktop" in
	kde)
		# Plasma's packages own /etc/xdg/kdeglobals and overwrite the copy
		# system_files laid down in the base stage, so the look-and-feel has to
		# be re-asserted here, after the install (#1008).
		/run/context/build_scripts/desktop/kde-set-look-and-feel.sh

		/run/context/build_scripts/checks/verify-branding-kde.sh "${IMAGE_NAME:-$desktop}"
		install -Dm0755 /run/context/build_scripts/checks/verify-branding-kde.sh \
			/usr/libexec/tunaos/verify-branding-kde
		BRANDING_EXTRA="ExecStart=-/usr/libexec/tunaos/verify-branding-kde ${IMAGE_NAME:-$desktop} --runtime"
		;;
	niri)
		/run/context/build_scripts/checks/verify-branding-niri.sh "${IMAGE_NAME:-$desktop}"
		install -Dm0755 /run/context/build_scripts/checks/verify-branding-niri.sh \
			/usr/libexec/tunaos/verify-branding-niri
		BRANDING_EXTRA="ExecStart=-/usr/libexec/tunaos/verify-branding-niri ${IMAGE_NAME:-$desktop} --runtime"
		;;
	esac
	# Wants=, NOT Requires=. With Requires=, a failed display manager takes
	# the contract down as DEPEND — which silences the one service built to
	# diagnose that exact failure: verify-desktop-experience --runtime has a
	# dm_inactive branch that ships `systemctl show` and the DM's journal
	# tail to the serial console. Both proof cells of run pair
	# 31204811851/31204818233 crash-looped lightdm and produced
	# desktop_contract=absent with zero journal evidence, because the
	# diagnostician was skipped alongside its patient. Wants= keeps the
	# pull-in and the After= ordering; a dead DM now yields
	# TUNAOS_DESKTOP_CONTRACT_FAIL reason=dm_inactive plus the journal,
	# instead of silence.
	cat >/usr/lib/systemd/system/tunaos-desktop-contract.service <<EOF
[Unit]
Description=Verify TunaOS ${desktop} desktop experience
# dconf-update.service compiles /etc/dconf/db/*.d keyfiles at boot. On bases
# where the compiled db is baked at build this is a no-op; on guppy:gnome the
# baked db was absent and the contract raced the compile at first boot,
# failing on "missing compiled dconf database" while dconf-update would have
# fixed it moments later (boot-gate run 32323551841). Order after it so the
# check judges the settled state — a genuinely broken dconf still fails.
After=display-manager.service dconf-update.service
Wants=dconf-update.service
Wants=display-manager.service

[Service]
Type=oneshot
ExecStart=/usr/libexec/tunaos/verify-desktop-experience ${desktop} --runtime
ExecStart=-/usr/libexec/tunaos/verify-branding ${IMAGE_NAME:-${desktop}} --runtime
${BRANDING_EXTRA}
ExecStart=-/usr/libexec/tunaos/e2e-runtime-checks ${desktop}
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=90

[Install]
WantedBy=graphical.target
EOF
	systemctl enable tunaos-desktop-contract.service
	;;
esac
