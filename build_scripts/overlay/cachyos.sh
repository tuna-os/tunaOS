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

# Do not upgrade the base image here: a full -Syu can install or update the
# stock linux package alongside linux-cachyos, leaving bootc with multiple
# kernel trees.  The image must have one kernel whose initramfs is unambiguous.
pacman -S --noconfirm --needed \
	cachyos-keyring cachyos-mirrorlist cachyos-settings \
	linux-cachyos linux-cachyos-headers tpm2-tss

# linux-cachyos is the kernel selected for CachyOS images.  Remove Arch's
# stock kernel after the replacement is installed; -Rdd is intentional here
# because the stock kernel's dependencies are also provided by the CachyOS
# kernel package, but pacman cannot infer that relationship from package
# metadata.
if pacman -Qq linux >/dev/null 2>&1; then
	pacman -Rdd --noconfirm linux
fi

# Mark as CachyOS-augmented for install-desktop.sh detection
install -D /dev/null /etc/cachyos-release
printf 'CachyOS\n' >/etc/cachyos-release

# Rebuild initramfs via dracut.  Do not use find | tail -1: directory order is
# unspecified, and selecting the wrong tree leaves the bootloader with a
# kernel that has no matching initramfs.
mapfile -t _module_dirs < <(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d ! -name '*.img' | sort -V)
if [[ "${#_module_dirs[@]}" -ne 1 ]]; then
	echo "ERROR: CachyOS overlay expected exactly one kernel module tree, found ${#_module_dirs[@]}: ${_module_dirs[*]}" >&2
	exit 1
fi
_kernel_dir="${_module_dirs[0]}"
_kernel="$(basename "${_kernel_dir}")"
dracut --force --omit "tpm2-tss" "${_kernel_dir}/initramfs.img" "${_kernel}"
pacman -Scc --noconfirm || true
