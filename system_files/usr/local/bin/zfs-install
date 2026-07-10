#!/usr/bin/env bash
# zfs-install — install Ubuntu 26.04 bootc image onto a ZFS root filesystem.
#
# Usage:
#   sudo zfs-install /dev/sdX [--pool-name rpool] [--imgref <ref>] [--encrypt]
#
# The live ISO filesystem itself is NOT ZFS — this script only sets up ZFS on
# the *installation target* disk.  The live session needs zfsutils-linux
# (provided by the base bootc image which this ISO is built FROM).
#
# Flow:
#   1. Wipe + GPT partition: 512M EFI + ZFS remainder
#   2. Create pool with -R /mnt/target (altroot keeps live-system root safe)
#   3. Create rpool/root (canmount=noauto) + rpool/var (canmount=noauto)
#      /home is NOT a separate dataset — bootc symlinks /home → /var/home
#   4. Mount ONLY rpool/root at /mnt/target; mount EFI; no /var pre-mount
#      (bootc install to-filesystem rejects targets with extra mounts)
#   5. bootc install to-filesystem with spl_hostid karg
#   6. Post-install: set canmount=on, write /etc/hostid + zpool.cache
#   7. Clean zpool export before reboot

set -euo pipefail

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

require_cmd() {
    for cmd in "$@"; do
        command -v "${cmd}" >/dev/null 2>&1 || die "Required command not found: ${cmd}"
    done
}

cleanup() {
    info "Cleaning up..."
    umount /mnt/target/boot/efi 2>/dev/null || true
    zpool export "${POOL_NAME}" 2>/dev/null || true
}

# ── args ──────────────────────────────────────────────────────────────────────

DISK=""
POOL_NAME="rpool"
IMGREF=""
ENCRYPTION=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --pool-name) POOL_NAME="$2"; shift 2 ;;
        --imgref)    IMGREF="$2";    shift 2 ;;
        --encrypt)   ENCRYPTION=1;   shift   ;;
        -*)          die "Unknown option: $1" ;;
        *)           DISK="$1";      shift ;;
    esac
done

[[ -n "${DISK}" ]]    || die "Usage: zfs-install /dev/sdX [--pool-name rpool] [--imgref <ref>] [--encrypt]"
[[ -b "${DISK}" ]]    || die "Not a block device: ${DISK}"
[[ "${EUID}" -eq 0 ]] || die "Must run as root"

require_cmd sgdisk mkfs.fat zpool zfs bootc

if [[ "${DISK}" =~ nvme|mmcblk|loop ]]; then
    EFI_PART="${DISK}p1"; ZFS_PART="${DISK}p2"
else
    EFI_PART="${DISK}1";  ZFS_PART="${DISK}2"
fi

if [[ -z "${IMGREF}" ]]; then
    if [[ -f /etc/bootc-installer/images.json ]]; then
        IMGREF=$(python3 -c "import json; print(json.load(open('/etc/bootc-installer/images.json'))['local_imgref'])" 2>/dev/null) || true
    fi
    [[ -n "${IMGREF}" ]] || IMGREF="ghcr.io/hanthor/ubuntu-26.04-desktop-bootc:latest"
fi

HOSTID_HEX=$(hostid 2>/dev/null || echo "00000000")

# ── confirm ───────────────────────────────────────────────────────────────────

cat <<EOF

  ┌─────────────────────────────────────────────────────────┐
  │  Ubuntu 26.04 ZFS root installer                       │
  ├─────────────────────────────────────────────────────────┤
  │  Disk:    ${DISK}
  │  Pool:    ${POOL_NAME}
  │  Image:   ${IMGREF}
  │  HostID:  0x${HOSTID_HEX}
  │  Encrypt: $([ ${ENCRYPTION} -eq 1 ] && echo yes || echo no)
  └─────────────────────────────────────────────────────────┘

  WARNING: All data on ${DISK} will be DESTROYED!

EOF
read -r -p "  Type 'yes' to continue: " CONFIRM
[[ "${CONFIRM}" == "yes" ]] || die "Aborted."

trap cleanup EXIT

# ── 1. Partition ──────────────────────────────────────────────────────────────

info "Partitioning ${DISK}..."
sgdisk --zap-all "${DISK}"
sgdisk -n1:0:+512M -t1:ef00 -c1:"EFI System" "${DISK}"
sgdisk -n2:0:0     -t2:bf00 -c2:"ZFS"         "${DISK}"
partprobe "${DISK}" && sleep 1
mkfs.fat -F32 -n EFI "${EFI_PART}"

# ── 2. Create ZFS pool ────────────────────────────────────────────────────────
#
# -R /mnt/target  altroot: all mount operations during this session are rooted
#                 under /mnt/target, not the live system's /.  Without this,
#                 `zfs mount rpool/root` (mountpoint=/) would clobber the live /.

info "Creating pool '${POOL_NAME}'..."

ZFS_OPTS=(
    -f
    -R /mnt/target
    -o ashift=12
    -O compression=lz4
    -O acltype=posixacl
    -O xattr=sa
    -O relatime=on
    -O normalization=formD
    -O dnodesize=auto
    -O canmount=off
    -O mountpoint=none
)

if [[ ${ENCRYPTION} -eq 1 ]]; then
    info "Encryption: you will be prompted for a passphrase."
    ZFS_OPTS+=( -O encryption=aes-256-gcm -O keylocation=prompt -O keyformat=passphrase )
fi

zpool create "${ZFS_OPTS[@]}" "${POOL_NAME}" "${ZFS_PART}"

# ── 3. Create datasets ────────────────────────────────────────────────────────
#
# rpool/root  mountpoint=/    — OS root
# rpool/var   mountpoint=/var — mutable state (/home lives here as /var/home)
#
# canmount=noauto on both: we mount root manually below; var is NOT mounted
# during install (bootc rejects targets with active submounts).
# After install we set canmount=on so the installed system mounts them.

zfs create -o mountpoint=/    -o canmount=noauto "${POOL_NAME}/root"
zfs create -o mountpoint=/var -o canmount=noauto "${POOL_NAME}/var"
zpool set bootfs="${POOL_NAME}/root" "${POOL_NAME}"

# ── 4. Mount root + EFI for install ──────────────────────────────────────────

info "Mounting install target..."
mkdir -p /mnt/target
zfs mount "${POOL_NAME}/root"      # → /mnt/target  (altroot in effect)
mkdir -p /mnt/target/boot/efi
mount "${EFI_PART}" /mnt/target/boot/efi

# ── 5. Install ────────────────────────────────────────────────────────────────
#
# spl_hostid  — embeds this machine's host ID in the boot entry so the generic
#               (hostonly=no) initramfs can import the pool on first boot without
#               the host ID mismatch that causes "pool may be in use" errors.
# rootfstype=zfs — hints to dracut's ZFS module which filesystem type to expect.
# root=ZFS=   — tells the ZFS dracut module which dataset is the root.

info "Installing '${IMGREF}'..."

bootc install to-filesystem \
    --source-imgref "${IMGREF}" \
    --root-mount-spec "ZFS=${POOL_NAME}/root" \
    --karg "rootfstype=zfs" \
    --karg "spl_hostid=0x${HOSTID_HEX}" \
    /mnt/target

# ── 6. Post-install metadata ──────────────────────────────────────────────────

info "Writing ZFS boot metadata..."

# Enable datasets for the installed system
zfs set canmount=on "${POOL_NAME}/root"
zfs set canmount=on "${POOL_NAME}/var"

# /etc/hostid — userspace ZFS identity (supplements spl_hostid karg)
mkdir -p /mnt/target/etc
if command -v zgenhostid >/dev/null 2>&1; then
    zgenhostid -f "${HOSTID_HEX}" && [[ -f /etc/hostid ]] && cp /etc/hostid /mnt/target/etc/hostid
elif [[ -f /etc/hostid ]]; then
    cp /etc/hostid /mnt/target/etc/hostid
fi

# zpool.cache — lets zfs-import-cache.service fast-import on subsequent boots
mkdir -p /mnt/target/etc/zfs
zpool set cachefile=/mnt/target/etc/zfs/zpool.cache "${POOL_NAME}"

# ── 7. Clean export ───────────────────────────────────────────────────────────
#
# Exporting the pool marks it clean so the installed system's initramfs can
# import it without needing -f (forced import).

info "Exporting pool..."
umount /mnt/target/boot/efi
zpool export "${POOL_NAME}"
trap - EXIT

info ""
info "Done! Boot entry: root-mount-spec=ZFS=${POOL_NAME}/root rootfstype=zfs spl_hostid=0x${HOSTID_HEX}"
info "Remove the live media and reboot."
