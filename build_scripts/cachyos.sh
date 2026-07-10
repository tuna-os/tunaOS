#!/usr/bin/env bash
# cachyos.sh — Install CachyOS kernel and repos on a Marlin (Arch) base.
set -xeuo pipefail

pacman -Syu --noconfirm --needed \
    cachyos-keyring cachyos-mirrorlist cachyos-settings \
    linux-cachyos linux-cachyos-headers

# Mark as CachyOS-augmented for install-desktop.sh detection
install -D /dev/null /etc/cachyos-release
printf 'CachyOS\n' > /etc/cachyos-release

mkinitcpio -P
pacman -Scc --noconfirm || true
