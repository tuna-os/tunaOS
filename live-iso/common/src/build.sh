#!/usr/bin/env bash

set -eoux pipefail

# Directory containing this script — used to locate desktop adapters.
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"

# ── Repository workarounds for CentOS Stream ────────────────────────────────

# Enable the same compose repos during our build that the centos-bootc image
# uses during its build.  This avoids downgrading packages in the image that
# have strict NVR requirements.
# See: build_scripts/00-workarounds.sh for the main image equivalent.
if grep -q "centos" /etc/os-release 2>/dev/null; then
	if ls /etc/yum.repos.d/centos*.repo 2>/dev/null; then
		echo "Configuring CentOS Compose repos with skip_if_unavailable"
		curl --retry 3 --fail -Lo "/etc/yum.repos.d/compose.repo" "https://gitlab.com/redhat/centos-stream/containers/bootc/-/raw/c10s/cs.repo"
		sed -i \
			-e "s@- (BaseOS|AppStream)@& - Compose@" \
			-e "s@\(baseos\|appstream\)@&-compose@" \
			-e "/^\[.*compose\]/a skip_if_unavailable=True" \
			/etc/yum.repos.d/compose.repo
		cat /etc/yum.repos.d/compose.repo
	fi
fi

# ── Live environment configuration ──────────────────────────────────────────
# Desktop-specific config lives in per-desktop adapter scripts so adding
# a new desktop only requires a new file — no monolith editing.

case "${DESKTOP_FLAVOR:-gnome}" in
	gnome*)
		source "${SCRIPT_DIR}/desktop-gnome.sh"
		;;
	kde*)
		source "${SCRIPT_DIR}/desktop-kde.sh"
		;;
	# COSMIC and Niri don't need additional live-environment config —
	# livesys-scripts handles autologin for both.
esac

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
ExecStart=/bin/bash -c 'id liveuser && echo "liveuser:$(openssl rand -base64 12)" | chpasswd'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
	systemctl enable liveiso-dev-ssh.service
fi

# ── E2E readiness marker ─────────────────────────────────────────────────────
# Install a oneshot unit that prints TUNAOS_LIVE_READY to /dev/console once
# the live environment is up. scripts/iso-e2e.sh and the iso-e2e CI workflow
# poll the QEMU serial log for this string to know they can proceed with
# install / SSH tests. Always installed — the marker is harmless in
# production ISOs (one journal line) and removing the unit at release time
# would break the e2e workflow we use to validate those very releases.

install -Dm0644 /src/tunaos-live-ready.service \
	/etc/systemd/system/tunaos-live-ready.service
systemctl enable tunaos-live-ready.service

# ── tuna-installer configuration ─────────────────────────────────────────────
# Drop /etc/tuna-installer/{recipe,images}.json so the installer knows which
# variant/flavor it is, points update tracking at the right GHCR tag, and
# presents a focused TunaOS image catalog (used when running standalone via
# the Flatpak outside of live-ISO mode).
#
# Offline install works automatically in live-ISO mode: fisherman detects
# /run/ostree-booted and calls bootc install directly against the running
# image — no network pull required. The imgref here is only used for
# day-2 update tracking after the system is installed.

_VARIANT="${VARIANT:-tunaos}"
_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
_IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io}"
_GHCR_REF="${_IMAGE_REGISTRY}/tuna-os/${_VARIANT}:${_FLAVOR}"

mkdir -p /etc/tuna-installer

# recipe.json — TunaOS branding + this variant's update-tracking imgref.
cat >/etc/tuna-installer/recipe.json <<EOF
{
  "distro_name": "TunaOS",
  "distro_logo": "org.tunaos.Installer",
  "imgref": "${_GHCR_REF}",
  "hostname": "tunaos",
  "needs_user_creation": true
}
EOF

# images.json — full TunaOS catalog for standalone Flatpak use.
# default_image points at this variant/flavor. Icons use the GResource paths
# already bundled in the installer binary.
python3 - "${_VARIANT}" "${_FLAVOR}" "${_IMAGE_REGISTRY}" <<'PYEOF'
import json, sys

variant, flavor = sys.argv[1], sys.argv[2]
base = f"{sys.argv[3]}/tuna-os" if len(sys.argv) > 3 else "ghcr.io/tuna-os"
default = f"{base}/{variant}:{flavor}"

VARIANTS = [
    ("yellowfin", "Yellowfin", "AlmaLinux Kitten 10"),
    ("albacore",  "Albacore",  "AlmaLinux 10"),
    ("skipjack",  "Skipjack",  "CentOS Stream 10"),
    ("bonito",    "Bonito",    "Fedora 43"),
]
FLAVORS = [
    ("gnome",   "GNOME"),
    ("kde",     "KDE Plasma"),
    ("niri",    "Niri"),
    ("cosmic",  "COSMIC"),
]

def variant_entry(vid, vname, vdesc):
    return {
        "name": vname,
        "subtitle": vdesc,
        "icon": f"resource:///org/tunaos/Installer/images/{vid}.svg",
        "children": [
            {
                "name": fname,
                "imgref": f"{base}/{vid}:{fid}",
                "icon": f"resource:///org/tunaos/Installer/images/{vid}.svg",
                "desc": f"TunaOS {vname} — {fname} desktop",
                "needs_user_creation": True,
            }
            for fid, fname in FLAVORS
        ],
    }

manifest = {
    "app_name": "TunaOS Installer",
    "default_image": default,
    "fallback_flatpaks": [
        "org.mozilla.firefox",
        "org.gnome.Console",
        "org.gnome.TextEditor",
    ],
    "images": [
        {
            "name": "TunaOS",
            "search_extra": "tunaos tuna",
            "children": [variant_entry(vid, vname, vdesc) for vid, vname, vdesc in VARIANTS],
        }
    ],
}

with open("/etc/tuna-installer/images.json", "w") as f:
    json.dump(manifest, f, indent=2)
print(f"tuna-installer: wrote images.json (default={default})")
PYEOF

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
