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

fe_autostart "Install to disk" --icon org.gnome.Setup \
	--stamp org.gnome.Setup:SetupWindow:bus-name --bus-name org.gnome.Setup \
	-- /usr/bin/gnome-setup
fe_stamp launcher
