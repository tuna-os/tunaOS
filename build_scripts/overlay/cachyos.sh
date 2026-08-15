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

# -Sy + -S, not -Syu: this runs mid-overlay on a published parent image, and a
# full upgrade here can bump the stock kernel too — a second moving kernel in a
# script whose whole job is to end up with exactly one. (Not what broke run
# 31766586852: `installing linux-cachyos` with no `upgrading linux` shows the
# parent's kernel was untouched there. This closes the latent version, not the
# observed one.) Same shape as overrides/nvidia-arch/20-nvidia.sh.
pacman -Sy --noconfirm
pacman -S --noconfirm --needed \
	cachyos-keyring cachyos-mirrorlist cachyos-settings \
	linux-cachyos linux-cachyos-headers tpm2-tss

# Mark as CachyOS-augmented for install-desktop.sh detection
install -D /dev/null /etc/cachyos-release
printf 'CachyOS\n' >/etc/cachyos-release

# ── one kernel, one initramfs, both named explicitly (tunaOS#1563) ───────────
#
# The parent image already ships the stock `linux` kernel (Containerfile.arch
# installs ${KERNEL_PKG}/${KERNEL_PKG}-headers), so installing linux-cachyos
# above leaves TWO module trees. This block used to end in:
#
#   dracut --force --omit tpm2-tss \
#     "$(find /usr/lib/modules -maxdepth 1 -type d | grep -v '\.img' | tail -1)/initramfs.img"
#
# `find` without `sort` returns readdir order, so which tree got the initramfs
# was a per-image coin flip. Run 31766586852 flipped it both ways in a single
# nightly — same script, same commit, five flavors:
#
#   gnome/kde/cosmic-cachyos -> /usr/lib/modules/7.1.8-arch1-3/initramfs.img
#   xfce/niri-cachyos        -> /usr/lib/modules/7.1.8-1-cachyos/initramfs.img
#
# and that split is exactly the split in the Gate failures: the three that
# wrote to the stock tree died in `bootc install` with "Computing boot digest:
# initramfs not found", the two that wrote to the cachyos tree installed but
# booted a kernel whose module tree disagreed and never reached
# graphical.target. Both presentations, one cause.
#
# Note `sort -V` would NOT have fixed it and must not be used here:
#
#   $ printf '6.17.1-arch1-1\n6.17.1-2-cachyos\n' | sort -V | tail -1
#   6.17.1-arch1-1
#
# version-sort puts the stock kernel last, so `sort -V | tail -1` is a
# deterministic wrong answer rather than a coin flip. The package is literally
# linux-cachyos and its module directory carries `cachyos`, so select by name.
KVER="$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d -name '*cachyos*' -printf '%f\n' 2>/dev/null | sort -V | tail -1)"
if [ -z "$KVER" ]; then
	echo "ERROR: linux-cachyos installed but no *cachyos* module directory exists" >&2
	echo "       under /usr/lib/modules — the kernel package layout changed." >&2
	find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d -printf '  %f\n' >&2 || true
	exit 1
fi
echo "==> target kernel: ${KVER}"

# Drop the stock kernel now that cachyos is in — the asahi.sh:179 pattern.
# -Rdd skips dep checks (nothing here needs a cascade) and this runs AFTER the
# install, so a failed linux-cachyos transaction leaves a bootable image rather
# than no kernel at all. Both the x86_64 and ARM stock names are tried because
# Containerfile.arch picks between them by $(uname -m).
for _stock in linux linux-headers linux-aarch64 linux-aarch64-headers; do
	pacman -Rdd --noconfirm "$_stock" 2>/dev/null || true
done

# Package removal is not enough: initramfs.img is generated, not packaged, so
# pacman leaves the stock tree behind with a stale initramfs in it. Delete any
# tree that is not the selected kernel, then PROVE only one remains — tunaOS#912
# is this exact cleanup silently not happening and an ambiguous-boot image
# getting published. A loud build failure beats a silently-wrong image.
find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d ! -name "$KVER" -exec rm -rf {} +
REMAINING_KVERS="$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d -printf '%f\n')"
REMAINING_COUNT="$(printf '%s\n' "$REMAINING_KVERS" | grep -c .)"
if [ "$REMAINING_COUNT" -ne 1 ] || [ "$REMAINING_KVERS" != "$KVER" ]; then
	echo "ERROR: expected exactly 1 kernel in /usr/lib/modules (${KVER}) after cleanup, found ${REMAINING_COUNT}:" >&2
	printf '%s\n' "$REMAINING_KVERS" >&2
	echo "ERROR: a stock kernel survived removal; bootc would pick between two trees (tunaOS#912, tunaOS#1563)." >&2
	exit 1
fi

# Rebuild initramfs via dracut. Path AND kernel version passed positionally —
# the same form overrides/nvidia-arch/20-nvidia.sh uses, which is the sibling
# Arch overlay whose five flavors passed their Gate in the run above. Naming
# the kernel means the output path can never disagree with what was built.
dracut --force --omit "tpm2-tss" "/usr/lib/modules/${KVER}/initramfs.img" "${KVER}"
pacman -Scc --noconfirm || true
