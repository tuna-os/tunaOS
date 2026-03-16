#!/usr/bin/env bash

set -eoux pipefail

IMAGE_INFO="$(cat /usr/share/ublue-os/image-info.json)"
IMAGE_TAG="$(jq -c -r '."image-tag"' <<<"$IMAGE_INFO")"
IMAGE_REF="$(jq -c -r '."image-ref"' <<<"$IMAGE_INFO")"
IMAGE_REF="${IMAGE_REF##*://}"

# PAYLOAD_REF is the containers-storage ref Anaconda will install from.
# It's set at build time by the build script and must match the
# --bootc-installer-payload-ref passed to image-builder-cli.
# Default to the registry ref from image-info.json if not overridden.
PAYLOAD_REF="${PAYLOAD_REF:-${IMAGE_REF}:${IMAGE_TAG}}"

# ── Live environment configuration ──────────────────────────────────────────

# Set up the GNOME dock for the installer
tee /usr/share/glib-2.0/schemas/zz2-tunaos-installer.gschema.override <<'EOF'
[org.gnome.shell]
welcome-dialog-last-shown-version='4294967295'
favorite-apps = ['liveinst.desktop', 'org.mozilla.firefox.desktop', 'org.gnome.Nautilus.desktop']
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

# ── Install Anaconda ─────────────────────────────────────────────────────────

# Remove old liveinst package; anaconda-live replaces it
dnf remove -y anaconda-liveinst || true

# Install EPEL (needed for some deps on EL10)
dnf install -y epel-release ||
	dnf install -y "https://dl.fedoraproject.org/pub/epel/epel-release-latest-10.noarch.rpm"

# Anaconda WebUI COPR (backport for EL10)
dnf copr enable -y jreilly1821/anaconda-webui

dnf install -y --nobest --allowerasing \
	libblockdev \
	libblockdev-lvm \
	libblockdev-dm \
	anaconda \
	anaconda-live \
	anaconda-webui \
	firefox \
	openssh-server \
	fuse-overlayfs

# Fix anaconda-webui desktop file pointing to wrong path
sed -i 's|/usr/libexec/webui-desktop|/usr/libexec/anaconda/webui-desktop|g' /bin/liveinst || true

# HOTFIX: Blivet/dasbus import error in Anaconda Storage Module (Python 3.12)
DISCOVER_PY=$(find /usr/lib*/python3.* -path "*/pyanaconda/modules/storage/iscsi/discover.py" 2>/dev/null | head -n 1)
if [ -n "$DISCOVER_PY" ]; then
	sed -i "s/from blivet.safe_dbus import SafeDBusError/from dasbus.error import DBusError as SafeDBusError/g" \
		"$DISCOVER_PY" || true
fi

# ── Anaconda profile ─────────────────────────────────────────────────────────

# Tag the OS so Anaconda's profile detection can match it
sed -i 's/^ID=.*/ID=tunaos/' /usr/lib/os-release
echo "VARIANT_ID=tunaos" >>/usr/lib/os-release

mkdir -p /etc/anaconda/profile.d
tee /etc/anaconda/profile.d/tunaos.conf <<'EOF'
[Profile]
profile_id = tunaos

[Profile Detection]
os_id = tunaos

[Network]
default_on_boot = FIRST_WIRED_WITH_LINK

[Bootloader]
efi_dir = centos
menu_auto_hide = True

[Storage]
file_system_type = xfs
default_partitioning =
    /     (min 5 GiB, max 70 GiB)
    /var  (min 5 GiB)

[User Interface]
hidden_spokes =
    NetworkSpoke
    PasswordSpoke
    UserSpoke
hidden_webui_pages =
    anaconda-screen-accounts

[Localization]
use_geolocation = False
EOF

# ── Kickstart ────────────────────────────────────────────────────────────────

mkdir -p /usr/share/anaconda/post-scripts

# Install from the embedded image in containers-storage
tee -a /usr/share/anaconda/interactive-defaults.ks <<EOF
ostreecontainer --url=${PAYLOAD_REF} --transport=containers-storage --no-signature-verification
%include /usr/share/anaconda/post-scripts/install-flatpaks.ks
EOF

# Copy Flatpaks installed on the live system to the installed system
tee /usr/share/anaconda/post-scripts/install-flatpaks.ks <<'EOF'
%post --erroronfail --nochroot
deployment="$(ostree rev-parse --repo=/mnt/sysimage/ostree/repo ostree/0/1/0)"
target="/mnt/sysimage/ostree/deploy/default/deploy/$deployment.0/var/lib/"
mkdir -p "$target"
rsync -aAXUHKP /var/lib/flatpak "$target"
%end
EOF

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

# ── EFI / ISO tooling ────────────────────────────────────────────────────────

# grub2-efi-x64-cdboot provides gcde64.efi needed by the ISO builder
dnf install -y grub2-efi-x64-cdboot

# image-builder expects EFI files under /boot/efi
mkdir -p /boot/efi
# grub2-efi-x64-cdboot on EL puts files in /usr/lib/efi
if [ -d /usr/lib/efi ]; then
	cp -av /usr/lib/efi/*/*/EFI /boot/efi/ 2>/dev/null || true
fi

# Tools needed inside the osbuild buildroot
dnf install -y xorriso isomd5sum squashfs-tools

# ── GRUB config for the ISO ──────────────────────────────────────────────────

mkdir -p /usr/lib/bootc-image-builder
# Write iso.yaml with the correct LABEL substituted
CDLABEL="${LABEL//-/_}" # CDLABEL can't have hyphens in some tools; use underscores
cat >/usr/lib/bootc-image-builder/iso.yaml <<EOF
label: "${LABEL}"
grub2:
  timeout: 10
  entries:
    - name: "Install ${LABEL}"
      linux: "/images/pxeboot/vmlinuz quiet rhgb root=live:CDLABEL=${CDLABEL} enforcing=0 rd.live.image"
      initrd: "/images/pxeboot/initrd.img"
EOF

# ── Cleanup ──────────────────────────────────────────────────────────────────

dnf clean all

# ── fuse-overlayfs for Anaconda container storage ────────────────────────────
# Required for Anaconda to deploy the bootc container image from the ISO

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
