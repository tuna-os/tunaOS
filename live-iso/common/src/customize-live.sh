#!/usr/bin/env bash
# customize-live.sh — tacklebox live_customize entrypoint for TunaOS ISOs.
#
# Runs inside a container of the flavor's bootc image before tacklebox
# squashes it (CAP_SYS_ADMIN + network; cwd = this directory). Everything
# here lands in the live squashfs ONLY — installed systems never see it.
# Pattern: projectbluefin/dakota-iso configure-live.sh.
#
# Responsibilities:
#   1. Detect the desktop from the image's session files
#   2. Source the desktop adapter (desktop-<D>.sh): autologin, no-sleep, pinning
#   3. Pre-install the desktop-matched installer Flatpak into the squash
#   4. fisherman symlink + polkit setup so the live session installs
#      without password prompts
#   5. Installer offline-stores config

set -exo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Desktop detection ──────────────────────────────────────────────────────
# TUNA_SESSION_ROOT lets the bats tests point detection at a fake root.
_SR="${TUNA_SESSION_ROOT:-}"
DESKTOP="gnome"
if [[ -f "${_SR}/usr/share/wayland-sessions/plasma.desktop" ]]; then
	DESKTOP="kde"
elif [[ -f "${_SR}/usr/share/wayland-sessions/niri.desktop" ]]; then
	DESKTOP="niri"
elif [[ -f "${_SR}/usr/share/wayland-sessions/cosmic.desktop" ]]; then
	DESKTOP="cosmic"
elif compgen -G "${_SR}/usr/share/xsessions/xfce*.desktop" >/dev/null; then
	DESKTOP="xfce"
fi
echo "customize-live: detected desktop=${DESKTOP}"

case "${DESKTOP}" in
kde) INSTALLER_APP="org.tunaos.InstallerKde" ;;
niri) INSTALLER_APP="org.tunaos.InstallerNiri" ;;
cosmic) INSTALLER_APP="org.tunaos.InstallerCosmic" ;;
xfce) INSTALLER_APP="org.tunaos.InstallerXfce" ;;
*) INSTALLER_APP="" ;; # gnome: upstream bootc-installer ships via its own channel
esac

# Test hook: report detection and stop before any system mutation.
if [[ "${TUNA_DETECT_ONLY:-0}" == "1" ]]; then
	echo "DETECTED ${DESKTOP} ${INSTALLER_APP:-none}"
	exit 0
fi

# ── 2. Desktop adapter (autologin, screen-lock, suspend masking) ─────────────
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/desktop-${DESKTOP}.sh"

# ── 3. Pre-install the installer Flatpak into the live squash ────────────────
# dbus is needed for flatpak's system helper inside the build container.
if [[ -n "${INSTALLER_APP}" ]]; then
	# bootc images intentionally ship an uninitialized machine-id.  Flatpak
	# starts a private D-Bus client during live-image customization, however,
	# and refuses to do so without a valid ID.  This only mutates the ephemeral
	# live squashfs; installed systems still receive their own machine-id.
	# Several bootc bases make /root a symlink into /var, whose target is not
	# mounted in tacklebox's customization container. Give D-Bus/Flatpak a
	# disposable, always-writable home instead of assuming /root exists.
	export HOME=/tmp/tuna-live-customize
	export XDG_CACHE_HOME="${HOME}/.cache"
	mkdir -p "${XDG_CACHE_HOME}" /run/dbus
	if [[ ! -s /etc/machine-id ]] || grep -qx 'uninitialized' /etc/machine-id; then
		rm -f /etc/machine-id
		dbus-uuidgen --ensure=/etc/machine-id
	fi
	mkdir -p /var/lib/dbus
	ln -sf /etc/machine-id /var/lib/dbus/machine-id
	dbus-daemon --system --fork --nopidfile || true

	flatpak remote-add --system --if-not-exists tuna-os \
		https://tunaos.org/flatpak/tuna-os.flatpakrepo
	# Flatpak also opens a session-bus connection even for a system install.
	# The headless tacklebox container has no DISPLAY, so autolaunch cannot
	# create one; provide an explicit short-lived session bus instead.
	dbus-run-session -- \
		flatpak install --system --noninteractive -y tuna-os "${INSTALLER_APP}"

	# ── 4a. fisherman on the host path ────────────────────────────────────
	# The frontends escalate via `flatpak-spawn --host pkexec
	# /usr/local/bin/fisherman`; expose the flatpak-bundled binary there.
	FISHERMAN_BIN=$(find "/var/lib/flatpak/app/${INSTALLER_APP}" \
		-path '*/files/bin/fisherman' -type f 2>/dev/null | head -1)
	if [[ -n "${FISHERMAN_BIN}" ]]; then
		mkdir -p /usr/local/bin
		ln -sf "${FISHERMAN_BIN}" /usr/local/bin/fisherman
	else
		echo "WARNING: fisherman not found inside ${INSTALLER_APP}" >&2
	fi
fi

# ── 4b. Polkit: passwordless install for the live session ────────────────────
# Policy override (allow_active=yes) + JS rule for liveuser, covering both the
# custom action and generic pkexec (dakota-iso #25 belt-and-suspenders).
mkdir -p /usr/share/polkit-1/actions
cat >/usr/share/polkit-1/actions/org.tunaos.Installer.policy <<'POLICYEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
  "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
  "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <action id="org.tunaos.Installer.install">
    <description>Install TunaOS to a disk</description>
    <message>Authentication is required to install an operating system</message>
    <icon_name>drive-harddisk</icon_name>
    <defaults>
      <allow_any>no</allow_any>
      <allow_inactive>no</allow_inactive>
      <allow_active>yes</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/local/bin/fisherman</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
POLICYEOF

mkdir -p /etc/polkit-1/rules.d
cat >/etc/polkit-1/rules.d/99-live-installer.rules <<'RULESEOF'
polkit.addRule(function(action, subject) {
    if ((action.id === "org.freedesktop.policykit.exec" ||
         action.id === "org.tunaos.Installer.install") &&
            subject.user === "liveuser" && subject.local) {
        return polkit.Result.YES;
    }
});
RULESEOF

# ── 5. Installer offline-stores config ────────────────────────────────────────
# Probe list the frontends read to find embedded OCI stores; missing paths
# are skipped, and the live-ISO self-install path needs no store at all.
mkdir -p /etc/tuna-installer
cat >/etc/tuna-installer/offline-stores <<'STORESEOF'
# OCI store roots probed by the TunaOS installer for offline images.
/usr/share/tuna-installer/oci-store
/var/lib/superiso-store
STORESEOF

# ── /var/tmp headroom ─────────────────────────────────────────────────────────
# The live overlay puts /var on a small RAM overlay; bootc needs real space
# in /var/tmp when staging an install (dakota-iso pattern).
cat >/usr/lib/systemd/system/var-tmp.mount <<'UNITEOF'
[Unit]
Description=Large tmpfs for /var/tmp in the live environment

[Mount]
What=tmpfs
Where=/var/tmp
Type=tmpfs
Options=size=8G,nr_inodes=1m

[Install]
WantedBy=local-fs.target
UNITEOF
systemctl enable var-tmp.mount

echo "customize-live: done (desktop=${DESKTOP}, installer=${INSTALLER_APP:-upstream})"
