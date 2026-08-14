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

# Install the CachyOS kernel without upgrading the entire base mid-overlay.
# A full -Syu can update the stock kernel as a side effect, leaving multiple
# module trees for the bootc/BLS generator to choose between.
pacman -S --noconfirm --needed \
	cachyos-keyring cachyos-mirrorlist cachyos-settings \
	linux-cachyos linux-cachyos-headers tpm2-tss

# The Arch base's stock linux package is not a usable fallback here: keeping
# it alongside linux-cachyos gives bootc two kernels but only one reliably
# prepared initramfs. Remove it before generating the CachyOS initramfs.
if pacman -Qq linux >/dev/null 2>&1; then
	pacman -Rdd --noconfirm linux
fi

# Mark as CachyOS-augmented for install-desktop.sh detection
install -D /dev/null /etc/cachyos-release
printf 'CachyOS\n' >/etc/cachyos-release

# Rebuild an initramfs for every remaining kernel tree. Never select one with
# find | tail: directory enumeration order is not stable, and bootc may select
# a different BLS kernel than the one that happened to receive the initramfs.
kernel_dirs=()
for kernel_dir in /usr/lib/modules/*; do
	[[ -d "$kernel_dir" ]] || continue
	[[ "${kernel_dir##*/}" == *.img ]] && continue
	kernel_dirs+=("$kernel_dir")
done
if ((${#kernel_dirs[@]} == 0)); then
	echo "ERROR: no kernel module directories remain after installing linux-cachyos" >&2
	exit 1
fi
for kernel_dir in "${kernel_dirs[@]}"; do
	dracut --force --omit "tpm2-tss" "${kernel_dir}/initramfs.img"
done
pacman -Scc --noconfirm || true
