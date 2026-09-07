#!/usr/bin/env bash
# Live ISO desktop adapter: GNOME
# Sourced by live-iso/common/src/build.sh for gnome* desktop flavors.
#
# Configures:
#   - GNOME dock favorites (FirstSetup, Firefox, Nautilus)
#   - Disable suspend/sleep (installer can't recover from S3)
#   - Compile gschemas

set -euo pipefail

# GDM autologin straight into the live session. Debian/Ubuntu read
# /etc/gdm3/, everyone else /etc/gdm/ — write whichever exists (both when
# neither does, harmlessly).
for _gdm_dir in /etc/gdm /etc/gdm3; do
	[[ -d "${_gdm_dir}" || "${_gdm_dir}" == "/etc/gdm" ]] || continue
	mkdir -p "${_gdm_dir}"
	tee "${_gdm_dir}/custom.conf" <<'GDMEOF'
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=liveuser
GDMEOF
done

# Set up the GNOME dock for the installer
tee /usr/share/glib-2.0/schemas/zz2-tunaos-installer.gschema.override <<'EOF'
[org.gnome.shell]
welcome-dialog-last-shown-version='4294967295'
favorite-apps = ['org.bootcinstaller.Installer.desktop', 'bootc-installer.desktop', 'firefox.desktop', 'org.gnome.Nautilus.desktop']
EOF

# Launch the installer at session start.
#
# GNOME had NO autostart entry while kde, cosmic and xfce all did, so on the
# gnome live ISO the installer was never started — the session came up in the
# empty Activities overview with the app merely pinned to the dash. Run
# 31171184497 recorded the result: 11 frames, 1 distinct visual state, 0/10
# transitions, and all six screen rows false. Nothing was broken; nothing had
# been launched.
#
# It went unnoticed because gnome was absent from installer-smoke.yml's flavor
# matrix (added in #1039), and that is the workflow whose whole job is to
# assert the installer process is running.
#
# GNOME deliberately starts a normal user session in Activities. An XDG
# autostart application does not dismiss that overview, so the installer maps
# behind Shell chrome and receives neither focus nor keyboard input. Install a
# live-session-only extension which closes the overview once Shell's startup
# animation completes. The launcher enables it in liveuser's volatile dconf
# before starting the installer; using `gnome-extensions enable` appends to the
# user's extension set instead of replacing the image's enabled extensions.
_gnome_live_extension="tunaos-live-installer@tunaos.org"
_gnome_live_extension_dir="/usr/share/gnome-shell/extensions/${_gnome_live_extension}"
mkdir -p "${_gnome_live_extension_dir}"
tee "${_gnome_live_extension_dir}/metadata.json" <<'METADATAEOF'
{
  "uuid": "tunaos-live-installer@tunaos.org",
  "name": "TunaOS Live Installer",
  "description": "Present the installer instead of the startup overview in the live session",
  "shell-version": ["45", "46", "47", "48", "49", "50", "51"]
}
METADATAEOF
tee "${_gnome_live_extension_dir}/extension.js" <<'EXTENSIONEOF'
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export default class TunaOSLiveInstallerExtension {
    enable() {
        // Hide now when the extension is enabled after startup, and again at
        // startup-complete when it is enabled while Shell is still animating.
        Main.layoutManager.connectObject(
            'startup-complete', () => Main.overview.hide(), this);
        Main.overview.hide();
    }

    disable() {
        Main.layoutManager.disconnectObject(this);
    }
}
EXTENSIONEOF

install -d /usr/libexec
tee /usr/libexec/tunaos-live-installer-gnome <<'LAUNCHEREOF'
#!/usr/bin/env bash
# Failure to load the convenience extension must not prevent installation.
gnome-extensions enable tunaos-live-installer@tunaos.org ||
    echo "tunaos-live-installer: could not suppress GNOME's startup overview" >&2
exec flatpak run org.bootcinstaller.Installer
LAUNCHEREOF
chmod 0755 /usr/libexec/tunaos-live-installer-gnome

# Deliberately no OnlyShowIn=, for the reason spelled out in desktop-cosmic.sh:
# systemd-xdg-autostart-generator gates on systemd-xdg-autostart-condition
# against XDG_CURRENT_DESKTOP, and a mismatch silently skips the unit.
mkdir -p /etc/xdg/autostart
tee /etc/xdg/autostart/org.tunaos.installer-live.desktop <<'DESKEOF'
[Desktop Entry]
Type=Application
Name=Install TunaOS
Exec=/usr/libexec/tunaos-live-installer-gnome
Icon=org.bootcinstaller.Installer
DESKEOF

# Disable suspend/sleep so the installer doesn't go to sleep mid-install
tee /usr/share/glib-2.0/schemas/zz3-tunaos-installer-power.gschema.override <<'EOF'
[org.gnome.settings-daemon.plugins.power]
sleep-inactive-ac-type='nothing'
sleep-inactive-battery-type='nothing'
sleep-inactive-ac-timeout=0
sleep-inactive-battery-timeout=0

[org.gnome.desktop.session]
idle-delay=uint32 0
EOF

# Not every base ships glib2-devel, and an unguarded call aborts the whole
# customize step under `set -e` (exit 127) — this is what broke the
# flounder/flounder-sid overlays. The override file above is still written;
# without recompilation it is simply inert.
if command -v glib-compile-schemas &>/dev/null; then
	glib-compile-schemas /usr/share/glib-2.0/schemas
else
	echo "desktop-gnome: glib-compile-schemas missing; power-settings override left uncompiled" >&2
fi
