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

# remora — local layering CLI (github.com/tuna-os/remora). Static Go binary,
# works on every base (dnf/zypper/pacman/apt). Version pinned for
# reproducible image builds; renovate can bump it.
REMORA_VERSION="v0.2.0"
REMORA_ARCH="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
curl --retry 3 --fail -L \
	"https://github.com/tuna-os/remora/releases/download/${REMORA_VERSION}/remora-linux-${REMORA_ARCH}" \
	-o "$DOWNLOADS_DIR/remora"
install -Dm0755 "$DOWNLOADS_DIR/remora" /usr/bin/remora
rm "$DOWNLOADS_DIR/remora"

# Treat the downloaded binary as an image contract, not merely a successful
# HTTP transfer. This catches wrong-architecture assets, truncated releases,
# and version drift before an image can be published.
REMORA_REPORTED_VERSION="$(remora --version)"
if [[ "${REMORA_REPORTED_VERSION}" != *"${REMORA_VERSION#v}"* ]]; then
	echo "ERROR: expected remora ${REMORA_VERSION}, got: ${REMORA_REPORTED_VERSION}" >&2
	exit 1
fi
install -d /usr/share/tunaos/experience-contracts
printf 'version=%s\nvalidated_at_build=true\n' "${REMORA_VERSION}" \
	>/usr/share/tunaos/experience-contracts/remora

# Generate initramfs image after installing Yellowfin branding because of Plymouth subpackage
# Set TunaOS Plymouth theme before rebuilding initramfs so dracut picks it up
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
	plymouth-set-default-theme tunaos
fi

# Disable system sleep/suspend to prevent VMs from suspending during walkthroughs
systemctl mask suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target || true

# Add the resume module so hibernation works. Live boot needs nothing
# here: tacklebox injects its embedded tbox-live/tbox-root dracut
# modules at ISO build time (tuna-os/tacklebox#90).
echo "add_dracutmodules+=\" resume \"" >/etc/dracut.conf.d/resume.conf 2>/dev/null || true
# Omit optional modules that aren't available in container builds
echo "omit_dracutmodules+=\" pcsc bluetooth pcmcia syslog \"" >/etc/dracut.conf.d/omit-optional.conf 2>/dev/null || true

# Update kernel module dependencies
depmod -a "$(find /lib/modules/ -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | sort | tail -1)"

KERNEL_SUFFIX=""
QUALIFIED_KERNEL="$(rpm -qa | grep -P 'kernel-(|'"$KERNEL_SUFFIX"'-)(\d+\.\d+\.\d+)' | sed -E 's/kernel-(|'"$KERNEL_SUFFIX"'-)//' | tail -n 1)"
export DRACUT_NO_XATTR=1
/usr/bin/dracut --tmpdir /tmp --no-hostonly --kver "$QUALIFIED_KERNEL" --reproducible --zstd -v --add ostree -f "/lib/modules/$QUALIFIED_KERNEL/initramfs.img"

printf "::endgroup::\n"
