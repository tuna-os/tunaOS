#!/usr/bin/env bash
# Pantheon (elementary) live session: gnome-setup, autostarted (tunaOS#4905).
# Contract: frontends/README.md. Run by install-frontend.sh.
set -euo pipefail
# shellcheck disable=SC1091
source "${MEDIUM_FRONTENDS:?run through install-frontend.sh}/lib.sh"
# shellcheck disable=SC1091
source "${MEDIUM_FRONTENDS}/gnome/install-gnome-setup.sh"
fe_init "$1" pantheon
fe_install_gnome_setup

# Pantheon images ship LightDM and no GDM. medium-live-setup only configures
# GDM and SDDM, so a Pantheon live boot reached a black screen with a valid
# liveuser and no login (desktop-pantheon.sh, measured on gurnard-pantheon).
# Prefer the X11 session: pantheon-wayland restarted every 3 seconds on the GPU
# runner (run 43443907569).
fe_live_setup_hook 50-pantheon-autologin <<'HOOKEOF'
#!/usr/bin/bash
set -euo pipefail
user="${1:?live user}"
session=pantheon
if [[ ! -f /usr/share/xsessions/pantheon.desktop ]]; then
    if [[ -f /usr/share/wayland-sessions/pantheon-wayland.desktop ]]; then
        session=pantheon-wayland
    else
        echo "pantheon-autologin: no pantheon session file found" >&2
        exit 1
    fi
fi
install -d /etc/lightdm/lightdm.conf.d
printf '[Seat:*]\nautologin-user=%s\nautologin-user-timeout=0\nautologin-session=%s\n' \
    "${user}" "${session}" >/etc/lightdm/lightdm.conf.d/90-medium-live-autologin.conf
groupadd -f autologin
usermod -aG autologin "${user}"
HOOKEOF

# Keep the machine awake and unlocked mid-install, as the GNOME launcher
# does: Pantheon's power and idle settings live in the same GNOME schemas.
fe_write 0755 /usr/libexec/medium-live-installer-pantheon <<'LAUNCHEOF'
#!/usr/bin/bash
gsettings set org.gnome.desktop.session idle-delay 0 || true
gsettings set org.gnome.desktop.screensaver lock-enabled false || true
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type nothing || true
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type nothing || true
exec /usr/libexec/medium-live-gnome-setup "$@"
LAUNCHEOF

fe_autostart "Install to disk" --icon org.gnome.Setup \
	--stamp org.gnome.Setup:SetupWindow:bus-name --bus-name org.gnome.Setup \
	-- /usr/libexec/medium-live-installer-pantheon
fe_stamp launcher
