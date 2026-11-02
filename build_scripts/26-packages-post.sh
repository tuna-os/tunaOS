#!/bin/bash

set -xeuo pipefail

printf "::group:: === 26 Packages Post ===\n"

MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

# Download directory - use /var/tmp to avoid tmpfs limitations
DOWNLOADS_DIR="/var/tmp/tunaos-downloads"
mkdir -p "$DOWNLOADS_DIR"

# Download JetBrainsMono tarball separately — large binary downloads can get
# corrupted under curl -Z parallel transfer (partial file on transient error).
curl --retry 3 --fail -L \
	"https://github.com/ryanoasis/nerd-fonts/releases/download/v3.4.0/JetBrainsMono.tar.xz" \
	-o "$DOWNLOADS_DIR/JetBrainsMono.tar.xz"

# Small assets are safe to batch in parallel.
curl --retry 3 --fail -Z \
	-o "$DOWNLOADS_DIR/bluefin.pdf" "https://github.com/ublue-os/bluefin-docs/releases/download/0.1/bluefin.pdf" \
	-o "$DOWNLOADS_DIR/flathub.flatpakrepo" "https://dl.flathub.org/repo/flathub.flatpakrepo"

# Install downloaded assets
install -Dm0644 -t /usr/share/doc/bluefin/ "$DOWNLOADS_DIR/bluefin.pdf"

# Install JetBrains Mono Nerd Font
mkdir -p /usr/share/fonts/JetBrainsMonoNerdFont
tar -xJf "$DOWNLOADS_DIR/JetBrainsMono.tar.xz" -C /usr/share/fonts/JetBrainsMonoNerdFont
if command -v fc-cache >/dev/null 2>&1; then
	fc-cache -f /usr/share/fonts/JetBrainsMonoNerdFont
fi
rm "$DOWNLOADS_DIR/JetBrainsMono.tar.xz"

# Add Flathub by default
mkdir -p /etc/flatpak/remotes.d
install -m0644 "$DOWNLOADS_DIR/flathub.flatpakrepo" /etc/flatpak/remotes.d/flathub.flatpakrepo

# remora — local layering CLI. Lives in its own script so bases that cannot
# run this one (Containerfile.opensuse skips the numbered scripts entirely —
# see install-remora.sh) can still install it from a single source of truth.
"$(dirname "$0")/install-remora.sh"

# Select the variant's Plymouth theme before the initramfs is rebuilt below,
# so dracut picks it up. The variant-to-theme table lives in
# plymouth-set-theme.sh, shared with every other base. No argument: the
# selector reads the canonical IMAGE_NAME_VARIANT itself. IMAGE_NAME is the
# publish name, "bonito" for bonito-rawhide, and passing it gave Rawhide
# Bonito's fishing-pole (tunaOS#4104).
"$(dirname "$0")/plymouth-set-theme.sh"

# Disable system sleep/suspend to prevent VMs from suspending during walkthroughs
systemctl mask suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target || true

# Add the resume module so hibernation works. Live boot needs nothing
# here: tacklebox injects its embedded tbox-live/tbox-root dracut
# modules at ISO build time (tuna-os/tacklebox#90).
echo "add_dracutmodules+=\" resume \"" >/etc/dracut.conf.d/resume.conf 2>/dev/null || true
# Omit optional modules that aren't available in container builds
echo "omit_dracutmodules+=\" pcsc bluetooth pcmcia syslog \"" >/etc/dracut.conf.d/omit-optional.conf 2>/dev/null || true
# Force virtio-gpu in: plymouth's dracut module only pulls simpledrm, so on QEMU virtio-vga the LUKS prompt never paints
echo "add_drivers+=\" virtio_gpu \"" >/etc/dracut.conf.d/virtio-gpu.conf 2>/dev/null || true

# /root is a symlink to var/roothome in bootc images, and the AlmaLinux
# bootc base ships it dangling: /var/roothome does not exist yet (it is
# created later by 99-cleanup.sh). dracut unconditionally replicates /root
# into the initramfs skeleton and dracut-install fails on the dangling
# link with `ERROR: installing '/root'`. The error is non-fatal (dracut
# continues and writes a good initramfs) but reads as a build failure in
# CI logs, so pre-create the target; same mkdir 99-cleanup.sh performs.
mkdir -p /var/roothome
chmod 0700 /var/roothome

# Update kernel module dependencies
depmod -a "$(find /lib/modules/ -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort | tail -1)"

KERNEL_SUFFIX=""
QUALIFIED_KERNEL="$(rpm -qa | grep -P 'kernel-(|'"$KERNEL_SUFFIX"'-)(\d+\.\d+\.\d+)' | sed -E 's/kernel-(|'"$KERNEL_SUFFIX"'-)//' | tail -n 1)"
export DRACUT_NO_XATTR=1
/usr/bin/dracut --tmpdir /tmp --no-hostonly --kver "$QUALIFIED_KERNEL" --reproducible --zstd -v --add ostree -f "/lib/modules/$QUALIFIED_KERNEL/initramfs.img"

# The splash plymouthd draws is the one dracut just copied in; prove it is
# this variant's, not a sibling's or the generic fish (tunaOS#4104). Exit 2 is
# an image with no plymouth or no script plugin, where the selector kept the
# distro splash on purpose: every EL10 base but hummingbird installs both
# strictly in 10-base-packages.sh, and hummingbird's --skip-unavailable set
# does not ask for plymouth-plugin-script. Report that loudly; fail the rest.
plymouth_rc=0
"$(dirname "$0")/checks/verify-plymouth-initramfs.sh" \
	"${IMAGE_NAME_VARIANT:-${IMAGE_NAME:-}}" "/lib/modules/$QUALIFIED_KERNEL/initramfs.img" || plymouth_rc=$?
if [[ "$plymouth_rc" -eq 2 ]]; then
	echo "::warning::no TunaOS boot splash in this image: plymouth or its script plugin is missing (see TUNAOS_PLYMOUTH_BLOCKED above)"
elif [[ "$plymouth_rc" -ne 0 ]]; then
	exit "$plymouth_rc"
fi

printf "::endgroup::\n"
