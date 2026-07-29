#!/usr/bin/env bash
# cachyos.sh — Install CachyOS kernel and repos on a Marlin (Arch) base.
set -xeuo pipefail

# Nothing registers the [cachyos] repo before this point, so `pacman -Syu
# cachyos-keyring ...` below fails with "target not found: cachyos-keyring".
# Register it the same way CachyOS's own installer (cachyos-repo.sh) does:
# fetch their repo bootstrap tarball, which imports the signing key and adds
# the [cachyos] section (+ v3/v4 variants) to pacman.conf itself.
# Initialize pacman keyring and populate archlinux keys
pacman-key --init || true
pacman-key --populate archlinux || true

# Fetch and install CachyOS keyring and mirrorlists directly
mirror_url="https://mirror.cachyos.org/repo/x86_64/cachyos"
pacman -U --noconfirm \
	"${mirror_url}/cachyos-keyring-20240331-1-any.pkg.tar.zst" \
	"${mirror_url}/cachyos-mirrorlist-27-1-any.pkg.tar.zst" \
	"${mirror_url}/cachyos-v3-mirrorlist-27-1-any.pkg.tar.zst" || true

# Add cachyos repository definitions to pacman.conf if missing
if ! grep -q "^\[cachyos\]" /etc/pacman.conf; then
	cat << 'EOF' >> /etc/pacman.conf

[cachyos]
Include = /etc/pacman.d/cachyos-mirrorlist
EOF
fi

pacman -Syu --noconfirm --needed \
	cachyos-keyring cachyos-mirrorlist cachyos-settings \
	linux-cachyos linux-cachyos-headers

# Mark as CachyOS-augmented for install-desktop.sh detection
install -D /dev/null /etc/cachyos-release
printf 'CachyOS\n' >/etc/cachyos-release

mkinitcpio -P
pacman -Scc --noconfirm || true
