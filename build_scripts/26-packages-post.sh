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

# Offline Yellowfin documentation
curl --retry 3 --fail -Lo "$DOWNLOADS_DIR/bluefin.pdf" https://github.com/ublue-os/bluefin-docs/releases/download/0.1/bluefin.pdf
install -Dm0644 -t /usr/share/doc/bluefin/ "$DOWNLOADS_DIR/bluefin.pdf"

# Install JetBrains Mono Nerd Font
curl --retry 3 --fail -Lo "$DOWNLOADS_DIR/JetBrainsMono.tar.xz" \
	"https://github.com/ryanoasis/nerd-fonts/releases/download/v3.4.0/JetBrainsMono.tar.xz"
mkdir -p /usr/share/fonts/JetBrainsMonoNerdFont
tar -xJf "$DOWNLOADS_DIR/JetBrainsMono.tar.xz" -C /usr/share/fonts/JetBrainsMonoNerdFont
fc-cache -f /usr/share/fonts/JetBrainsMonoNerdFont
rm "$DOWNLOADS_DIR/JetBrainsMono.tar.xz"

# Add Flathub by default
mkdir -p /etc/flatpak/remotes.d
curl --retry 3 --fail -o /etc/flatpak/remotes.d/flathub.flatpakrepo "https://dl.flathub.org/repo/flathub.flatpakrepo"

# Generate initramfs image after installing Yellowfin branding because of Plymouth subpackage
# Set TunaOS Plymouth theme before rebuilding initramfs so dracut picks it up
plymouth-set-default-theme tunaos

# Add resume module so that hibernation works
echo "add_dracutmodules+=\" resume \"" >/etc/dracut.conf.d/resume.conf
# Omit optional modules that aren't available in container builds
echo "omit_dracutmodules+=\" pcsc bluetooth pcmcia syslog \"" >/etc/dracut.conf.d/omit-optional.conf

# Update kernel module dependencies
depmod -a "$(find /lib/modules/ -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort | tail -1)"

KERNEL_SUFFIX=""
QUALIFIED_KERNEL="$(rpm -qa | grep -P 'kernel-(|'"$KERNEL_SUFFIX"'-)(\d+\.\d+\.\d+)' | sed -E 's/kernel-(|'"$KERNEL_SUFFIX"'-)//' | tail -n 1)"
export DRACUT_NO_XATTR=1
/usr/bin/dracut --tmpdir /tmp --no-hostonly --kver "$QUALIFIED_KERNEL" --reproducible --zstd -v --add ostree -f "/lib/modules/$QUALIFIED_KERNEL/initramfs.img"

printf "::endgroup::\n"
