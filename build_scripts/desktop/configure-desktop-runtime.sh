#!/usr/bin/env bash

set -euo pipefail

desktop="${1:?usage: configure-desktop-runtime.sh <gnome|kde|niri|cosmic|xfce>}"

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
	# This tests the CLAIM, not the package, and that distinction is the
	# whole safety argument. Fedora and EL10 install cosmic-greeter too, and
	# their cosmic cells are green today *because* `systemctl enable greetd`
	# succeeds there — which is direct evidence their scriptlets leave the
	# alias alone. Keying off "is cosmic-greeter installed" would have
	# repointed those images; keying off the symlink cannot.
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
	if systemctl list-unit-files lightdm.service --no-legend 2>/dev/null | grep -q '^lightdm.service'; then
		dm=lightdm
	else
		dm=greetd
	fi
	;;
*) exit 0 ;;
esac

systemctl enable "${dm}.service"
systemctl set-default graphical.target

# Every desktop family ships an explicit runtime contract plus the
# snosi-derived installed-system TAP checks (harvested from the serial
# console by scripts/iso-e2e.sh; the checks ExecStart is non-fatal).
case "$desktop" in
gnome | kde | niri | cosmic | xfce)
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
	cat >/usr/lib/systemd/system/tunaos-desktop-contract.service <<EOF
[Unit]
Description=Verify TunaOS ${desktop} desktop experience
After=display-manager.service
Requires=display-manager.service

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
