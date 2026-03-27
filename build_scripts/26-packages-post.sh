#!/bin/bash

set -xeuo pipefail

printf "::group:: === 26 Packages Post ===\n"

MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

# Offline Yellowfin documentation
curl --retry 3 -Lo /tmp/bluefin.pdf https://github.com/ublue-os/bluefin-docs/releases/download/0.1/bluefin.pdf
install -Dm0644 -t /usr/share/doc/bluefin/ /tmp/bluefin.pdf

# Install JetBrains Mono Nerd Font
curl --retry 3 -Lo /tmp/JetBrainsMono.zip \
	"https://github.com/ryanoasis/nerd-fonts/releases/download/v3.4.0/JetBrainsMono.zip"
mkdir -p /usr/share/fonts/JetBrainsMonoNerdFont
unzip -o /tmp/JetBrainsMono.zip -d /usr/share/fonts/JetBrainsMonoNerdFont \
	"*.ttf" -x "*Windows*"
fc-cache -f /usr/share/fonts/JetBrainsMonoNerdFont
rm /tmp/JetBrainsMono.zip

# Add Flathub by default
mkdir -p /etc/flatpak/remotes.d
curl --retry 3 -o /etc/flatpak/remotes.d/flathub.flatpakrepo "https://dl.flathub.org/repo/flathub.flatpakrepo"

# Generate initramfs image after installing Yellowfin branding because of Plymouth subpackage
# Set TunaOS Plymouth theme before rebuilding initramfs so dracut picks it up
plymouth-set-default-theme tunaos
# Add resume module so that hibernation works
echo "add_dracutmodules+=\" resume \"" >/etc/dracut.conf.d/resume.conf
# Omit optional modules that aren't available in container builds
echo "omit_dracutmodules+=\" pcsc bluetooth pcmcia syslog \"" >/etc/dracut.conf.d/omit-optional.conf
KERNEL_SUFFIX=""
QUALIFIED_KERNEL="$(rpm -qa | grep -P 'kernel-(|'"$KERNEL_SUFFIX"'-)(\d+\.\d+\.\d+)' | sed -E 's/kernel-(|'"$KERNEL_SUFFIX"'-)//' | tail -n 1)"
/usr/bin/dracut --tmpdir /tmp --no-hostonly --kver "$QUALIFIED_KERNEL" --reproducible --zstd -v --add ostree -f "/lib/modules/$QUALIFIED_KERNEL/initramfs.img"

printf "::endgroup::\n"
