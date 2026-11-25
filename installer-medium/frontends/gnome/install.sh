#!/usr/bin/env bash
# GNOME live session: gnome-setup, autostarted (tunaOS#4905).
# Contract: frontends/README.md. Run by install-frontend.sh.
set -euo pipefail
# shellcheck disable=SC1091
source "${MEDIUM_FRONTENDS:?run through install-frontend.sh}/lib.sh"
# shellcheck disable=SC1091
source "${MEDIUM_FRONTENDS}/gnome/install-gnome-setup.sh"
fe_init "$1" gnome
fe_install_gnome_setup

# GNOME starts in the Activities overview, and an autostart window maps behind
# Shell chrome without focus or keyboard input (desktop-gnome.sh, run
# 31171184497: the installer never came to the front). A live-only extension
# closes the overview; the launcher enables it in the live user's own dconf.
ext=tunaos-live-installer@tunaos.org
fe_write 0644 "/usr/share/gnome-shell/extensions/${ext}/metadata.json" <<METADATAEOF
{
  "uuid": "${ext}",
  "name": "TunaOS live installer",
  "description": "Show the installer instead of the startup overview in the live session",
  "shell-version": ["45", "46", "47", "48", "49", "50", "51"]
}
METADATAEOF
fe_write 0644 "/usr/share/gnome-shell/extensions/${ext}/extension.js" <<'EXTENSIONEOF'
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export default class TunaOSLiveInstallerExtension {
    enable() {
        Main.layoutManager.connectObject(
            'startup-complete', () => Main.overview.hide(), this);
        Main.overview.hide();
    }

    disable() {
        Main.layoutManager.disconnectObject(this);
    }
}
EXTENSIONEOF

# A failure to load the convenience extension must not stop the install. The
# power settings keep the machine awake mid-install (S3 cannot recover).
fe_write 0755 /usr/libexec/medium-live-installer-gnome <<'LAUNCHEOF'
#!/usr/bin/bash
gnome-extensions enable tunaos-live-installer@tunaos.org ||
    echo "medium-live-installer-gnome: could not suppress the startup overview" >&2
gsettings set org.gnome.shell welcome-dialog-last-shown-version 4294967295 || true
gsettings set org.gnome.desktop.session idle-delay 0 || true
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type nothing || true
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type nothing || true
exec /usr/bin/gnome-setup "$@"
LAUNCHEOF

# org.gnome.Setup owns its bus name once it runs. A bus name proves the
# process started, not that a frame reached the screen, so the signal is the
# weakest honest claim (README, "Readiness stamp").
fe_autostart "Install to disk" --icon org.gnome.Setup \
	--stamp org.gnome.Setup:SetupWindow:bus-name --bus-name org.gnome.Setup \
	-- /usr/libexec/medium-live-installer-gnome
fe_stamp launcher
