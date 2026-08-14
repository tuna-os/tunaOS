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

# Fetch and lsign CachyOS key from key server
pacman-key --recv-keys F3B607488DB35A47 --keyserver keyserver.ubuntu.com || true
pacman-key --lsign-key F3B607488DB35A47 || true

# Ensure pacman database directory structure exists
mkdir -p /var/lib/pacman /usr/lib/sysimage/lib/pacman

# Fetch and install CachyOS keyring and mirrorlists directly
mirror_url="https://mirror.cachyos.org/repo/x86_64/cachyos"
tmpconf="$(mktemp)"
cp /etc/pacman.conf "$tmpconf"
sed -i 's/SigLevel *=.*/SigLevel = Never/' "$tmpconf" || true
pacman -U --noconfirm --config "$tmpconf" \
	"${mirror_url}/cachyos-keyring-20240331-1-any.pkg.tar.zst" \
	"${mirror_url}/cachyos-mirrorlist-27-1-any.pkg.tar.zst" \
	"${mirror_url}/cachyos-v3-mirrorlist-27-1-any.pkg.tar.zst"
rm -f "$tmpconf"

# Add cachyos repository definitions to pacman.conf if missing
if ! grep -q "^\[cachyos\]" /etc/pacman.conf; then
	cat <<'EOF' >>/etc/pacman.conf

[cachyos]
Include = /etc/pacman.d/cachyos-mirrorlist
EOF
fi

# This stage's parent image already has a kernel: Containerfile.arch's base
# build detects the [cachyos] repo in pacman.conf to decide KERNEL_PKG, but
# that repo isn't registered until the block above runs, in THIS later
# overlay stage — so the base build always installed stock `linux` (this
# overlay is x86_64-only, unlike asahi's aarch64-only marlin path) and
# already baked it an initramfs. Installing linux-cachyos without removing
# it left two kernel module trees on the image (tunaOS#1563), and the plain
# `pacman -Syu` below could independently bump the stock kernel to a third.
# Remove it first, the same way asahi.sh removes marlin's aarch64 stock
# kernel before installing linux-asahi.
pacman -Rdd --noconfirm linux linux-headers 2>/dev/null || true

pacman -Sy --noconfirm --needed \
	cachyos-keyring cachyos-mirrorlist cachyos-settings \
	linux-cachyos linux-cachyos-headers tpm2-tss

# Mark as CachyOS-augmented for install-desktop.sh detection
install -D /dev/null /etc/cachyos-release
printf 'CachyOS\n' >/etc/cachyos-release

# Rebuild initramfs via dracut for every kernel module tree actually present,
# not a `find | tail -1` guess (tunaOS#1563): readdir order is unspecified,
# so which tree got the initramfs was a per-image gamble. When bootc's
# BLS/composefs setup picked a different entry than dracut did, install
# failed with "initramfs not found"; when the gamble half-landed, the
# booted kernel and its module tree disagreed and boot stalled before
# graphical.target. The stock kernel is removed above, so normally only the
# cachyos tree remains — looping keeps this correct even if that ever stops
# holding, instead of re-introducing the same guess with different odds.
mapfile -t _cachyos_moddirs < <(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d ! -name '*.img')
if [[ "${#_cachyos_moddirs[@]}" -eq 0 ]]; then
	echo "ERROR: no kernel module directory found under /usr/lib/modules" >&2
	exit 1
fi
for _moddir in "${_cachyos_moddirs[@]}"; do
	dracut --force --omit "tpm2-tss" "${_moddir}/initramfs.img"
done
unset _cachyos_moddirs _moddir

pacman -Scc --noconfirm || true
