#!/usr/bin/env bash
# cachyos.sh — Install CachyOS kernel and repos on a Marlin (Arch) base.
set -xeuo pipefail

# Nothing registers the [cachyos] repo before this point, so `pacman -Syu
# cachyos-keyring ...` below fails with "target not found: cachyos-keyring".
# Register it the same way CachyOS's own installer (cachyos-repo.sh) does:
# fetch their repo bootstrap tarball, which imports the signing key and adds
# the [cachyos] section (+ v3/v4 variants) to pacman.conf itself.
tmpdir="$(mktemp -d)"
curl -fsSL https://mirror.cachyos.org/cachyos-repo.tar.xz -o "$tmpdir/cachyos-repo.tar.xz"
tar -C "$tmpdir" -xf "$tmpdir/cachyos-repo.tar.xz"
(cd "$tmpdir/cachyos-repo" && ./cachyos-repo.sh)
rm -rf "$tmpdir"

pacman -Syu --noconfirm --needed \
	cachyos-keyring cachyos-mirrorlist cachyos-settings \
	linux-cachyos linux-cachyos-headers

# Mark as CachyOS-augmented for install-desktop.sh detection
install -D /dev/null /etc/cachyos-release
printf 'CachyOS\n' >/etc/cachyos-release

mkinitcpio -P
pacman -Scc --noconfirm || true
