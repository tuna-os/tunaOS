#!/usr/bin/env bash
# Sourced by gnome/install.sh when it runs for Tuna Desktop.
#
# Tuna Desktop's session (tuna-session, tuna-os/tuna-desktop) runs no XDG
# autostart entries: it starts its own compositor and shell and pulls only
# the GNOME Settings Daemon targets (share/systemd/user/tuna-session.target).
# On bonito:tuna the live session came up and nothing started the installer
# (run 45731860657: liveuser on seat0, no medium-live-installer process,
# usb-1-live-boot.png shows the overview only). So the live medium also
# starts the launcher as a user unit that tuna-session.target wants. Both
# start paths run the launcher with --once, so a session that honours
# both still shows one installer.

fe_tuna_session_start() {
	local entry="${FE_ROOT}${FE_AUTOSTART}" exec_line
	exec_line="$(sed -n 's/^Exec=//p' "${entry}")"
	[[ "${exec_line}" == "${FE_LAUNCHER} "* ]] || fe_die "unexpected autostart Exec: ${exec_line}"
	exec_line="${FE_LAUNCHER} --once ${exec_line#"${FE_LAUNCHER} "}"
	sed -i "s|^Exec=.*|Exec=${exec_line}|" "${entry}"

	fe_write 0644 /usr/lib/systemd/user/medium-live-installer-tuna.service <<UNITEOF
[Unit]
Description=TunaOS live: start the installer in the Tuna Desktop session
ConditionKernelCommandLine=tunaos.live
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=exec
ExecStart=${exec_line}
Restart=no
UNITEOF
	fe_write 0644 /usr/lib/systemd/user/tuna-session.target.d/50-medium-live-installer.conf <<'DROPEOF'
[Unit]
Wants=medium-live-installer-tuna.service
DROPEOF
}
