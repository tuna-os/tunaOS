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

# Remove stock kernel packages (linux, linux-headers) if present so only linux-cachyos remains.
# linux-cachyos provides "linux" / "linux-headers", so --noconfirm would decline conflict resolution
# if installed alongside stock linux.
pacman -Rdd --noconfirm linux linux-headers 2>/dev/null || true

pacman -S --noconfirm --needed \
	cachyos-keyring cachyos-mirrorlist cachyos-settings \
	linux-cachyos linux-cachyos-headers tpm2-tss

# Mark as CachyOS-augmented for install-desktop.sh detection
install -D /dev/null /etc/cachyos-release
printf 'CachyOS\n' >/etc/cachyos-release

# Rebuild initramfs via dracut for every kernel installed in /usr/lib/modules
for kdir in /usr/lib/modules/*/; do
	[[ -d "$kdir" ]] || continue
	kver="$(basename "$kdir")"
	dracut --force --omit "tpm2-tss" "${kdir}/initramfs.img" "${kver}"
done

pacman -Scc --noconfirm || true
