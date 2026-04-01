#!/usr/bin/env bash

set -eoux pipefail

# ── Live environment configuration ──────────────────────────────────────────

if [[ "${DESKTOP_FLAVOR:-gnome}" == gnome* ]]; then
	# Set up the GNOME dock for the installer
	tee /usr/share/glib-2.0/schemas/zz2-tunaos-installer.gschema.override <<'EOF'
[org.gnome.shell]
welcome-dialog-last-shown-version='4294967295'
favorite-apps = ['org.tunaos.FirstSetup.desktop', 'firefox.desktop', 'org.gnome.Nautilus.desktop']
EOF

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

	glib-compile-schemas /usr/share/glib-2.0/schemas
fi

# ── Disable TunaOS services not needed in the live/installer env ─────────────

systemctl disable rpm-ostree-countme.service || true
systemctl disable tailscaled.service || true
systemctl disable uupd.timer || true
systemctl disable ublue-system-setup.service || true
systemctl disable check-sb-key.service || true
systemctl disable brew-setup.service || true
systemctl disable brew-upgrade.timer || true
systemctl disable brew-update.timer || true
systemctl --global disable podman-auto-update.timer || true
systemctl --global disable ublue-user-setup.service || true
# auditd fails in the live overlay environment (audit netlink unavailable)
systemctl mask auditd.service audit-rules.service || true

# Fix resolv.conf permissions — in the live overlay the file can be written
# with mode 0700 by NetworkManager, blocking DNS for non-root processes.
mkdir -p /etc/NetworkManager/dispatcher.d
tee /etc/NetworkManager/dispatcher.d/99-fix-resolv-perms.sh <<'EOF'
#!/bin/bash
chmod 644 /etc/resolv.conf 2>/dev/null || true
EOF
chmod 755 /etc/NetworkManager/dispatcher.d/99-fix-resolv-perms.sh

# ── Dev: enable sshd for local testing ───────────────────────────────────────
# Only active when ENABLE_SSHD=1 (passed via `just live-iso dev=1`).
# Never enabled in production ISO builds.

if [ "${ENABLE_SSHD:-0}" = "1" ]; then
	echo "==> DEV: enabling sshd for local testing"
	systemctl enable sshd.service

	# Allow password auth (liveuser password set at runtime by oneshot below)
	mkdir -p /etc/ssh/sshd_config.d
	tee /etc/ssh/sshd_config.d/99-liveiso-dev.conf <<'EOF'
 PasswordAuthentication yes
 PermitRootLogin no
EOF

	# Oneshot that runs after livesys.service creates liveuser,
	# then sets the password to "live" so SSH can authenticate normally.
	tee /etc/systemd/system/liveiso-dev-ssh.service <<'EOF'
[Unit]
Description=Set liveuser password for dev SSH access
After=livesys.service
Requires=livesys.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'id liveuser && echo "liveuser:live" | chpasswd'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
	systemctl enable liveiso-dev-ssh.service
fi

# ── Install tunaos-first-setup (TunaOS Installer) ────────────────────────────

# glib2 may be version-locked to a GNOME COPR on EL10. Enable the matching
# COPR so glib2-devel resolves against the installed glib2 version.
#   gnome50  → jreilly1821/c10s-gnome-50-fresh (glib2 >= 2.86)
#   gnome49  → jreilly1821/c10s-gnome-49       (glib2 >= 2.84, < 2.86)
_glib2_minor=$(rpm -q --queryformat '%{VERSION}' glib2 2>/dev/null | awk -F. '{print $2+0}')
GNOME_COPR=""
if [[ "${DESKTOP_FLAVOR:-gnome}" == "gnome50" ]]; then
	GNOME_COPR="jreilly1821/c10s-gnome-50-fresh"
elif [[ "$_glib2_minor" -ge 84 ]]; then
	GNOME_COPR="jreilly1821/c10s-gnome-49"
fi
[[ -n "$GNOME_COPR" ]] && dnf -y copr enable "$GNOME_COPR"

# Install dependencies for the installer and live environment
dnf install -y \
	python3-gobject gtk4 libadwaita \
	glib2-devel \
	python3-pytz libgweather \
	parted cryptsetup dosfstools xfsprogs e2fsprogs btrfs-progs \
	fuse-overlayfs \
	firefox \
	openssh-server \
	meson python3-devel gettext \
	git

# Disable COPR again — only needed for glib2-devel resolution
[[ -n "$GNOME_COPR" ]] && dnf -y copr disable "$GNOME_COPR"

# Build and install tunaos-first-setup from source
git clone https://github.com/tuna-os/first-setup /tmp/first-setup
cd /tmp/first-setup
meson setup build --prefix=/usr
meson install -C build
cd /
rm -rf /tmp/first-setup

# Show the installer in the dock — the upstream desktop file sets NoDisplay=true
# to hide it from app grids on installed systems, but in the live ISO it must
# be visible so users can launch it from the dash.
sed -i 's/^NoDisplay=true/NoDisplay=false/' /usr/share/applications/org.tunaos.FirstSetup.desktop

# Remove build tools — no longer needed at runtime
dnf remove -y meson gcc python3-devel git || true

# ── dracut-live (live boot initramfs) ────────────────────────────────────────

# Create the directory that /root is symlinked to (needed in some containers)
mkdir -p "$(realpath /root)"

dnf install -y dracut-live

# Find the installed kernel version
kernel=$(find /lib/modules -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort -V | tail -n 1)
if [ -z "$kernel" ]; then
	echo "ERROR: could not find kernel in /lib/modules" >&2
	exit 1
fi
echo "Building initramfs for kernel: ${kernel}"

DRACUT_NO_XATTR=1 dracut -v --force --zstd --no-hostonly \
	--add "dmsquash-live dmsquash-live-autooverlay" \
	"/usr/lib/modules/${kernel}/initramfs.img" "${kernel}"

# livesys-scripts set up the live desktop session
dnf install -y livesys-scripts
sed -i "s/^livesys_session=.*/livesys_session=${DESKTOP_FLAVOR:-gnome}/" /etc/sysconfig/livesys
systemctl enable livesys.service livesys-late.service

# ── Inject missing livesys session modules for COSMIC and Niri ───────────────
# EPEL's livesys-scripts lags behind Fedora — livesys-cosmic and livesys-niri
# are absent from the EL10 package. Write them inline if not already present.

SESSIONS_DIR=/usr/libexec/livesys/sessions.d
mkdir -p "$SESSIONS_DIR"

# livesys-cosmic: ported from Fedora livesys-scripts PR #23 (ngompa)
# Appends [initial_session] to cosmic-greeter.toml so liveuser autologs in.
if [[ ! -f "${SESSIONS_DIR}/livesys-cosmic" ]]; then
	cat >"${SESSIONS_DIR}/livesys-cosmic" <<'LIVESYS_COSMIC'
#!/bin/bash
# livesys-cosmic — autologin for COSMIC live sessions
if [ -f /etc/greetd/cosmic-greeter.toml ]; then
    cat >> /etc/greetd/cosmic-greeter.toml <<'TOML_EOF'

[initial_session]
user = "liveuser"
command = "cosmic-session"
TOML_EOF
fi
LIVESYS_COSMIC
	chmod 755 "${SESSIONS_DIR}/livesys-cosmic"
fi

# livesys-niri: adds [initial_session] to greetd's config.toml for niri-session
if [[ ! -f "${SESSIONS_DIR}/livesys-niri" ]]; then
	cat >"${SESSIONS_DIR}/livesys-niri" <<'LIVESYS_NIRI'
#!/bin/bash
# livesys-niri — autologin for Niri live sessions via greetd
if [ -f /etc/greetd/config.toml ]; then
    cat >> /etc/greetd/config.toml <<'TOML_EOF'

[initial_session]
user = "liveuser"
command = "niri-session"
TOML_EOF
fi
LIVESYS_NIRI
	chmod 755 "${SESSIONS_DIR}/livesys-niri"
fi

# ── EFI / ISO tooling ────────────────────────────────────────────────────────

# grub2-efi-x64-cdboot provides gcde64.efi needed by the ISO builder
dnf install -y grub2-efi-x64-cdboot

# image-builder expects EFI files under /boot/efi
mkdir -p /boot/efi
# Kitten/el10-kitten: shim ships in /usr/lib/efi/shim/*/EFI/
if [ -d /usr/lib/efi ]; then
	cp -av /usr/lib/efi/*/*/EFI /boot/efi/ 2>/dev/null || true
fi
# AlmaLinux 10 stable: shim ships via bootupd in /usr/lib/bootupd/updates/EFI/
if [ -d /usr/lib/bootupd/updates/EFI ]; then
	cp -av /usr/lib/bootupd/updates/EFI /boot/efi/ 2>/dev/null || true
fi

# Tools needed inside the osbuild buildroot
dnf install -y xorriso isomd5sum squashfs-tools

# ── GRUB config for the ISO ──────────────────────────────────────────────────

mkdir -p /usr/lib/bootc-image-builder
# Write iso.yaml with the correct LABEL substituted
CDLABEL="${LABEL//-/_}" # ISO labels can't have hyphens; use underscores
cat >/usr/lib/bootc-image-builder/iso.yaml <<EOF
label: "${CDLABEL}"
grub2:
  timeout: 10
  entries:
    - name: "Install ${LABEL}"
      linux: "/images/pxeboot/vmlinuz quiet rhgb root=live:CDLABEL=${CDLABEL} tunaos.live=1 enforcing=0 rd.live.image"
      initrd: "/images/pxeboot/initrd.img"
EOF

# ── Cleanup ──────────────────────────────────────────────────────────────────

dnf clean all

# ── fuse-overlayfs for container storage ─────────────────────────────────────
# Unified storage (enabled via bootc experimental flag) means the booted image
# is already accessible in podman container storage — no copy-to-storage step
# needed. fuse-overlayfs is still required because the live overlay environment
# does not support native overlayfs mounts.

if [ ! -f /etc/containers/storage.conf ] && [ -f /usr/share/containers/storage.conf ]; then
	cp /usr/share/containers/storage.conf /etc/containers/storage.conf
fi

# Enable fuse-overlayfs (needed in the live environment where overlayfs is not available)
sed -i 's|^# mount_program = "/usr/bin/fuse-overlayfs"|mount_program = "/usr/bin/fuse-overlayfs"|' \
	/etc/containers/storage.conf
if ! grep -q '^mount_program = "/usr/bin/fuse-overlayfs"' /etc/containers/storage.conf; then
	sed -i 's|^# mount_program = .*|mount_program = "/usr/bin/fuse-overlayfs"|' \
		/etc/containers/storage.conf
fi
