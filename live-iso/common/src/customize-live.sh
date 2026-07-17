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
# gnome has no TunaOS-branded frontend fork; ship upstream bootc-installer
# directly, fetched the same way projectbluefin/dakota-iso does it (see
# install-flatpaks.sh there) rather than from the tuna-os Flatpak remote.
*) INSTALLER_APP="org.bootcinstaller.Installer" ;;
esac

# Test hook: report detection and stop before any system mutation.
if [[ "${TUNA_DETECT_ONLY:-0}" == "1" ]]; then
	echo "DETECTED ${DESKTOP} ${INSTALLER_APP:-none}"
	exit 0
fi

# ── 2. Desktop adapter (autologin, screen-lock, suspend masking) ─────────────
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/desktop-${DESKTOP}.sh"

# ── 2b. containers-storage: offline payload store (tacklebox-built) ─────────
# tacklebox's BuildOfflineStore() assembles an overlay-driver
# containers-storage graphroot of the payload image into
# LiveOS/store.squashfs.img on the ISO. Mount it at
# /var/lib/superiso-store and register it as an additionalimagestore so
# fisherman (bootcViaContainer path) finds it with a `containers-storage:`
# transport ref instead of pulling the same bytes over the network.
# Pattern: projectbluefin/dakota-iso's configure-live.sh, adapted for
# tacklebox's separate-store format.
#
# Use a oneshot service rather than a .mount unit: the escape encoding
# in mount unit filenames (\\x2d for hyphens) has proven fragile across
# systemd versions. A simple ExecStart=mount is more reliable.
STORE_MOUNT="/var/lib/superiso-store"
mkdir -p "$STORE_MOUNT"
cat >/usr/lib/systemd/system/tunaos-offline-store.service <<'UNITEOF'
[Unit]
Description=Mount tacklebox offline image store
DefaultDependencies=no
Before=local-fs.target
ConditionPathExists=/run/initramfs/live/LiveOS/store.squashfs.img

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/mount -o ro,nodev /run/initramfs/live/LiveOS/store.squashfs.img /var/lib/superiso-store
ExecStop=/usr/bin/umount /var/lib/superiso-store

[Install]
WantedBy=local-fs.target
UNITEOF
mkdir -p /etc/systemd/system/local-fs.target.wants
ln -sf /usr/lib/systemd/system/tunaos-offline-store.service \
	/etc/systemd/system/local-fs.target.wants/tunaos-offline-store.service

# The base image's /etc/containers/storage.conf may not exist in the
# customize container (bootc images ship uninitialized storage), and the
# driver may auto-detect as "btrfs" (EL10 default). The offline store is
# ALWAYS overlay, and additionalimagestores silently ignores stores with
# a different driver.  Write a complete drop-in that forces overlay and
# registers the mounted store — this works regardless of the base image's
# storage.conf state.
mkdir -p /etc/containers/storage.conf.d
cat >/etc/containers/storage.conf.d/99-tunaos-offline-store.conf <<'CONFEOF'
[storage]
driver = "overlay"
runroot = "/run/containers/storage"

[storage.options]
additionalimagestores = ["/var/lib/superiso-store"]

[storage.options.overlay]
mount_program = "/usr/bin/fuse-overlayfs"
CONFEOF

# Also write the driver + mount_program into the main storage.conf as a
# belt-and-suspenders measure, in case the drop-in isn't read.
mkdir -p /etc/containers
if [[ -f /etc/containers/storage.conf ]]; then
	if grep -q '^driver' /etc/containers/storage.conf; then
		sed -i 's/^driver *=.*/driver = "overlay"/' /etc/containers/storage.conf
	fi
fi
if [[ -f /etc/containers/storage.conf ]] && ! grep -q 'mount_program' /etc/containers/storage.conf; then
	cat >>/etc/containers/storage.conf <<'STOREOF'

[storage.options.overlay]
mount_program = "/usr/bin/fuse-overlayfs"
STOREOF
fi

# Dev/E2E media only: the normal published-image policy keeps SSH disabled.
# tacklebox creates liveuser during boot, so install a oneshot that sets its
# temporary test password after livesys and before the SSH daemon starts.
if [[ -f "${SCRIPT_DIR}/.enable-sshd" ]]; then
	SSH_UNIT=""
	# systemctl enable refuses to operate on a "linked unit file" (a symlink
	# under /usr/lib/systemd/system/, as opposed to an Alias= in [Install]).
	# Debian/Ubuntu's openssh-server ships sshd.service as exactly that kind
	# of compat symlink to the real ssh.service unit — require a real
	# (non-symlink) file so that case falls through to ssh.service below.
	[[ -f /usr/lib/systemd/system/sshd.service && ! -L /usr/lib/systemd/system/sshd.service ]] && SSH_UNIT="sshd.service"
	[[ -z "$SSH_UNIT" && -f /usr/lib/systemd/system/ssh.service ]] && SSH_UNIT="ssh.service"
	if [[ -z "$SSH_UNIT" ]]; then
		echo "ERROR: dev ISO requested but no SSH service is installed" >&2
		exit 1
	fi
	mkdir -p /etc/ssh/sshd_config.d /usr/lib/systemd/system \
		/etc/systemd/system/tunaos-live-ready.service.d
	cat >/etc/ssh/sshd_config.d/90-tunaos-live-e2e.conf <<'EOF'
PasswordAuthentication yes
PermitEmptyPasswords no
EOF
	cat >/usr/lib/systemd/system/tunaos-live-ssh-credentials.service <<EOF
[Unit]
Description=Configure temporary TunaOS live E2E SSH credentials
After=livesys.service
Before=${SSH_UNIT}

[Service]
Type=oneshot
ExecStart=/bin/sh -euxc 'getent passwd liveuser >/dev/null || useradd --create-home --user-group --shell /bin/bash liveuser; echo liveuser:live | chpasswd'
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=${SSH_UNIT}
EOF
	cat >/etc/systemd/system/tunaos-live-ready.service.d/10-ssh-credentials.conf <<'EOF'
[Unit]
Requires=tunaos-live-ssh-credentials.service
After=tunaos-live-ssh-credentials.service
EOF
	systemctl enable tunaos-live-ssh-credentials.service "$SSH_UNIT"

	# fisherman (the LUKS/TPM install backend) runs as root over a
	# non-interactive SSH command, so sudo has no TTY to prompt on. Grant
	# liveuser NOPASSWD sudo — dev/E2E media only, matching
	# projectbluefin/dakota-iso's debug=1 live-env setup (liveuser has
	# NOPASSWD sudo there too). Production images never enable sshd, so
	# liveuser never gets a login there.
	mkdir -p /etc/sudoers.d
	echo 'liveuser ALL=(ALL) NOPASSWD: ALL' >/etc/sudoers.d/90-tunaos-live-e2e
	chmod 0440 /etc/sudoers.d/90-tunaos-live-e2e
fi

# ── 3. Pre-install the installer Flatpak into the live squash ────────────────
# dbus is needed for flatpak's system helper inside the build container.
if [[ -n "${INSTALLER_APP}" ]]; then
	# Minimal containers (grouper/apt in particular) have no locale beyond
	# POSIX/C, which is strictly ASCII. glib's path handling requires a
	# UTF-8-capable locale even for ASCII paths in this codepath — without
	# one, flatpak fails with "Pathname can't be converted from UTF-8 to
	# current locale." C.UTF-8 is a built-in glibc locale, no locale-gen
	# needed, present on both apt and dnf bases.
	export LANG=C.UTF-8
	export LC_ALL=C.UTF-8
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
		# systemd-machine-id-setup (core systemd, always present) rather than
		# dbus-uuidgen — some flavors (niri, cosmic) don't pull in the dbus
		# package that ships dbus-uuidgen, but every systemd-based image has
		# systemd-machine-id-setup.
		systemd-machine-id-setup
	fi
	mkdir -p /var/lib/dbus
	ln -sf /etc/machine-id /var/lib/dbus/machine-id
	dbus-daemon --system --fork --nopidfile || true

	if ! command -v flatpak &>/dev/null; then
		echo "ERROR: flatpak not installed; cannot pre-install ${INSTALLER_APP}" >&2
		exit 1
	fi

	# The installer apps (tuna-os-hosted and upstream bootc-installer alike)
	# declare a GNOME/Freedesktop runtime dependency that isn't published on
	# the tuna-os remote itself — only the apps are. `flatpak install`
	# resolves missing runtime refs from any configured remote, so add
	# flathub here too; without it, install fails with "requires the
	# runtime org.gnome.Platform/... which was not found".
	flatpak remote-add --system --if-not-exists flathub \
		https://dl.flathub.org/repo/flathub.flatpakrepo

	# Flatpak also opens a session-bus connection even for a system install.
	# The headless tacklebox container has no DISPLAY, so autolaunch cannot
	# create one; provide an explicit short-lived session bus instead. Spun
	# up directly with dbus-daemon (already required above for the system
	# bus) rather than the dbus-run-session wrapper — some flavors (niri,
	# cosmic) don't pull in the package that ships dbus-run-session.
	SESSION_BUS_SOCK="${HOME}/session-bus.sock"
	dbus-daemon --session --fork --nopidfile --address="unix:path=${SESSION_BUS_SOCK}"
	export DBUS_SESSION_BUS_ADDRESS="unix:path=${SESSION_BUS_SOCK}"
	if [[ "${INSTALLER_APP}" == "org.bootcinstaller.Installer" ]]; then
		# gnome: mirrors projectbluefin/dakota-iso's install-flatpaks.sh —
		# download the upstream release bundle and import it into a
		# throwaway local ostree repo. `flatpak install --bundle` in a
		# container build only creates the installer-origin: remote ref, not
		# the deploy/ ref that `flatpak run`/`flatpak list` need; installing
		# from a local file:// remote goes through the full deploy pipeline.
		# Primary source: projectbluefin/bootc-installer (upstream). Fallback:
		# tuna-os/tuna-installer, which mirrors the same app ID as a release
		# asset.
		INSTALLER_FLATPAK_FILE="/tmp/bootc-installer.flatpak"
		if ! curl --retry 3 --fail --location \
			"https://github.com/projectbluefin/bootc-installer/releases/latest/download/org.bootcinstaller.Installer.flatpak" \
			-o "${INSTALLER_FLATPAK_FILE}" 2>/dev/null; then
			echo "projectbluefin/bootc-installer unavailable, falling back to tuna-os/tuna-installer..."
			curl --retry 3 --fail --location \
				"https://github.com/tuna-os/tuna-installer/releases/latest/download/org.bootcinstaller.Installer.flatpak" \
				-o "${INSTALLER_FLATPAK_FILE}"
		fi
		INSTALLER_LOCAL_REPO="/tmp/installer-local-repo"
		ostree init --repo="${INSTALLER_LOCAL_REPO}" --mode=archive-z2
		flatpak build-import-bundle "${INSTALLER_LOCAL_REPO}" "${INSTALLER_FLATPAK_FILE}"
		rm -f "${INSTALLER_FLATPAK_FILE}"
		flatpak remote-add --system --no-gpg-verify installer-local "file://${INSTALLER_LOCAL_REPO}"
		flatpak install --system --noninteractive installer-local "${INSTALLER_APP}"
		flatpak remote-delete --system --force installer-local || true
		rm -rf "${INSTALLER_LOCAL_REPO}"

		# A container-build install (no flatpak-system-helper daemon) creates
		# the deployment directory but omits the 'active' symlink inside the
		# branch directory, leaving the app unreachable to flatpak run/list.
		# Reproduce the symlink a normal installation would create.
		_app_arch_dir="/var/lib/flatpak/app/${INSTALLER_APP}/x86_64"
		for _branch_dir in "${_app_arch_dir}"/*/; do
			_branch_dir="${_branch_dir%/}"
			[[ -d "${_branch_dir}" ]] || continue
			if [[ ! -L "${_branch_dir}/active" ]]; then
				_hash=$(find "${_branch_dir}" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | head -1)
				if [[ -n "${_hash}" ]]; then
					ln -sfn "${_hash}" "${_branch_dir}/active"
					echo "Created active symlink: ${_branch_dir}/active → ${_hash}"
				fi
			fi
		done
	else
		flatpak remote-add --system --if-not-exists tuna-os \
			https://tunaos.org/flatpak/tuna-os.flatpakrepo
		flatpak install --system --noninteractive -y tuna-os "${INSTALLER_APP}"
	fi

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
