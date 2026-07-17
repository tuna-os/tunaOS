#!/usr/bin/env bash

set -euo pipefail

desktop="${1:?usage: configure-desktop-runtime.sh <gnome|kde|niri|cosmic|xfce>}"

# Desktop packages are installed in later Containerfile stages than the base
# service setup. Enable their display manager only after its unit exists.
case "$desktop" in
gnome) dm=gdm ;;
kde) dm=sddm ;;
niri | cosmic) dm=greetd ;;
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
	/run/context/build_scripts/checks/verify-desktop-experience.sh "$desktop"
	install -Dm0755 /run/context/build_scripts/checks/verify-desktop-experience.sh \
		/usr/libexec/tunaos/verify-desktop-experience
	install -Dm0755 /run/context/build_scripts/checks/e2e-runtime-checks.sh \
		/usr/libexec/tunaos/e2e-runtime-checks
	cat >/usr/lib/systemd/system/tunaos-desktop-contract.service <<EOF
[Unit]
Description=Verify TunaOS ${desktop} desktop experience
After=display-manager.service
Requires=display-manager.service

[Service]
Type=oneshot
ExecStart=/usr/libexec/tunaos/verify-desktop-experience ${desktop} --runtime
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
