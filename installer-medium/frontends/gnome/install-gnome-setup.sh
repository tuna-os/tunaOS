#!/usr/bin/env bash
# Shared by the gnome and pantheon installers: put the built gnome-setup into
# ROOT. Usage: install-gnome-setup.sh ROOT DESKTOP (needs fe_init done by the
# caller's sourcing, so it is sourced, not executed).
#
# Drops what a medium must not carry: the GNOME session units (the live user's
# session autostarts gnome-setup instead), the desktop file (an installed
# system must not offer an installer), and gnome-setup's own polkit rule, which
# grants real systemd actions that fishermand never asks about. The polkit
# rule for the install lives in live/usr/share/polkit-1/rules.d.

fe_install_gnome_setup() {
	local payload="${MEDIUM_PAYLOAD:?run through build-frontend.sh first}/gnome-setup"
	local stage
	[[ -x "${payload}/usr/bin/gnome-setup" ]] || fe_die "no built gnome-setup in ${payload}"
	stage="$(mktemp -d)"
	cp -a "${payload}/." "${stage}/"
	rm -rf "${stage}/usr/lib/systemd/user" \
		"${stage}/usr/share/applications/org.gnome.Setup.desktop" \
		"${stage}/usr/share/polkit-1/rules.d/20-gnome-setup.rules"
	fe_install_tree "${stage}"
	rm -rf "${stage}"
	fe_install 0644 "${MEDIUM_FRONTENDS}/gnome/pages.conf" /usr/lib/gnome-setup/pages.conf
}
