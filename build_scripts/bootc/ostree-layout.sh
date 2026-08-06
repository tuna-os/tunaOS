#!/usr/bin/env bash
# ostree-layout.sh — lay out the bootc/ostree filesystem every variant needs.
#
# WHY THIS EXISTS
#
# A bootc image has to end up with the same shape whatever built it: a wiped
# /var, a /sysroot, and the seven top-level paths that are really aliases into
# /var. Three Containerfiles spelled that out by hand — Arch once, Debian once,
# Gentoo TWICE (the `system` and `desktop` stages carry byte-identical 25-line
# RUN blocks) — so the same layout was written four times in this repo.
#
# Four copies of a list is four chances to drop an entry, and one had:
#
#                        /root  /home  /opt  /srv  /mnt  /usr/local
#   Containerfile.arch     y      y      y     y     y       y
#   Containerfile.debian   y      y      y     y     y       y
#   Containerfile.gentoo   y      y      y     -     -       -
#
# All three `rm -rf /srv /opt /mnt /usr/local` on the way in. Gentoo never put
# /srv, /mnt or /usr/local back, while still declaring /var/srv, /var/mnt and
# /var/usrlocal in tmpfiles.d — so guppy ships with those three paths simply
# absent and their /var targets orphaned. Nothing about Gentoo makes that
# correct; it is a transcription gap, and it is exactly what a fourth copy of a
# list is for. Sharing the list closes it.
#
# WHAT STAYS IN THE CONTAINERFILE
#
# Anything genuinely per-distro: relocating the package database out of /var
# (dpkg on Debian, portage on Gentoo, both of which must happen BEFORE the wipe
# below), pacman cache removal, Gentoo's /dev pruning. This script is the part
# that is the same everywhere, and it is deliberately not a plugin system.
#
# USAGE
#   ostree-layout.sh
#
# TUNAOS_COMPOSEFS=no writes `enabled = no` in prepare-root.conf, for a
# traditional ostree image (EL10). Default is yes.

set -euo pipefail
printf "::group:: === bootc ostree layout ===\n"

# Prefix for every path this script touches. Empty in a build; the tests point
# it at a fixture tree. Same hook as TUNAOS_SYSROOT in dracut-config.sh.
R="${TUNAOS_SYSROOT:-}"

COMPOSEFS="${TUNAOS_COMPOSEFS:-yes}"
case "$COMPOSEFS" in
yes | no) ;;
*)
	echo "ERROR: TUNAOS_COMPOSEFS must be yes or no, got '${COMPOSEFS}'" >&2
	exit 1
	;;
esac

# The aliases, and where each points. Listed once so nothing can carry a
# partial set. /usr/local is two levels down, hence the extra ../.
declare -a ALIASES=(
	"root:var/roothome"
	"home:var/home"
	"opt:var/opt"
	"srv:var/srv"
	"mnt:var/mnt"
	"usr/local:../var/usrlocal"
)

# ── 1. clear the aliases and /boot ───────────────────────────────────────────
# These are real directories in the base image; they become symlinks below.
for entry in "${ALIASES[@]}"; do
	rm -rf "${R}/${entry%%:*}"
done
rm -rf "${R}/boot"

# ── 2. wipe /var, but never a mount point ────────────────────────────────────
# /var can hold mount points inherited from overlayfs layers (rpm and dnf state
# on Fedora parents). rm -rf on one fails the layer, so skip anything mounted.
for d in "${R}"/var/* "${R}"/var/.[!.]*; do
	[ -d "$d" ] && ! mountpoint -q "$d" 2>/dev/null && rm -rf "$d" 2>/dev/null || true
done

# ── 3. rebuild the skeleton ──────────────────────────────────────────────────
mkdir -p "${R}/sysroot" "${R}/boot" "${R}/usr/lib/ostree" "${R}/var"

# The /var targets must EXIST at image-build time, not only in tmpfiles.d.
# Package maintainer scripts in later layers probe the aliases with
# `[ ! -d ... ] && mkdir` (Debian's base-files postinst does this to /mnt), and
# mkdir on a dangling symlink fails with EEXIST and takes the layer with it.
#
# /var/tmp specifically: tacklebox rebuilds the live-ISO initramfs against the
# published image, and dracut --tmpdir defaults to /var/tmp — an absent one
# fails the ISO build with "Invalid tmpdir '/var/tmp'".
mkdir -p "${R}/var/tmp" "${R}/var/roothome" "${R}/var/home" \
	"${R}/var/opt" "${R}/var/srv" "${R}/var/mnt" "${R}/var/usrlocal"
chmod 1777 "${R}/var/tmp"
chmod 0700 "${R}/var/roothome"

# ── 4. the aliases ───────────────────────────────────────────────────────────
ln -sfnT sysroot/ostree "${R}/ostree"
for entry in "${ALIASES[@]}"; do
	link="${entry%%:*}"
	target="${entry#*:}"
	mkdir -p "$(dirname "${R}/${link}")"
	ln -sfnT "$target" "${R}/${link}"
done

# New accounts must land in /var/home, not the /home symlink's notional path.
# Only Debian and Gentoo shipped this line; the file is absent on some bases,
# so it is conditional rather than assumed.
if [[ -f "${R}/etc/default/useradd" ]]; then
	sed -i 's|^HOME=.*|HOME=/var/home|' "${R}/etc/default/useradd"
fi

# ── 5. tmpfiles: recreate the /var targets after a factory reset ─────────────
mkdir -p "${R}/usr/lib/tmpfiles.d"
{
	echo "d /var/opt 0755 root root -"
	echo "d /var/home 0755 root root -"
	echo "d /var/srv 0755 root root -"
	echo "d /var/mnt 0755 root root -"
	echo "d /var/usrlocal 0755 root root -"
	echo "d /var/roothome 0700 root root -"
	echo "d /var/tmp 1777 root root -"
	echo "d /run/media 0755 root root -"
} >"${R}/usr/lib/tmpfiles.d/bootc-base-dirs.conf"

# ── 6. prepare-root.conf ─────────────────────────────────────────────────────
# The declaration that makes the root composefs. dracut-config.sh reads this
# file to decide whether the initramfs needs the erofs driver, so this must be
# written BEFORE the initramfs is built — see the ordering note in each
# Containerfile.
printf '[composefs]\nenabled = %s\n\n[sysroot]\nreadonly = true\n' "$COMPOSEFS" \
	>"${R}/usr/lib/ostree/prepare-root.conf"

echo "--- ${R}/usr/lib/ostree/prepare-root.conf ---"
cat "${R}/usr/lib/ostree/prepare-root.conf"
printf "::endgroup::\n"
