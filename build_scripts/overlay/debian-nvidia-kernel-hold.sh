#!/usr/bin/env bash
# debian-nvidia-kernel-hold.sh <kver> — on a flounder/flounder-sid *-nvidia
# overlay, swap the image kernel for the newest one in the Debian archive
# that the archive's nvidia-kernel-dkms can actually build against.
# Called by overrides/nvidia-debian/20-nvidia.sh after `apt-get update` (the
# driver version is only visible once non-free is enabled), so it lives
# outside overrides/ where run_buildscripts_for would run it on its own.
#
# WHY. Debian sid moved linux-image-amd64 to 7.2.7 (by 2026-09-24) while
# nvidia-kernel-dkms stayed at 550.163.01, and that module does not compile
# against 7.2 (tunaOS#2696, run 36083457907, all three flounder-sid *-nvidia):
#   nvidia/os-interface.c:753:5: error: implicit declaration of function
#   'strncpy' [-Wimplicit-function-declaration]
# Measured in debian:sid on 2026-09-25, no newer Debian driver fixes it:
#   nvidia-kernel-dkms      550.163.01-5.1 (sid)          7.2.7: FAIL  7.1.13: builds
#   nvidia-open-kernel-dkms 550.163.01-4   (sid)          7.2.7: FAIL (__vm_flags, in_irq)
#   nvidia-kernel-dkms      555.58.02-3    (experimental) 7.2.7: FAIL (VMA_LOCK_OFFSET)
# Nothing newer was in any Debian suite (madison), and NVIDIA's own apt repo
# is not on the PACKAGE-SOURCING.md allowlist. So the kernel follows the
# driver, the way overrides/nvidia/10-kernel-swap.sh aligns the RPM kernel
# to its akmods kmod — from the same official Debian archive, no new source.
#
# Then Debian fixed the driver (tunaOS#3692, #3685). 550.163.01-6 (sid,
# uploaded 2026-11-01) backports the strncpy and drm_atomic_commit_struct
# changes "to fix kernel module build for Linux 7.2", and sid dropped every
# kernel at or below 7.1, so the 7.1 ceiling above became unsatisfiable and
# all three flounder-sid *-nvidia cells failed nightly. Measured in debian:sid
# on 2026-11-06: nvidia-kernel-dkms 550.163.01-6 builds on 7.2.15+deb14-amd64
# (`dkms status`: installed). The ceiling is therefore keyed on the Debian
# revision, not just the upstream version: 550.163.01-1..-5.x stay at 7.1,
# 550.163.01-6 and later are measured to 7.2.
#
# The ceiling is keyed on the driver's version, so a Debian driver
# upload this table does not know about builds against the shipped kernel
# unchanged; if that fails, dkms fails the build as it always did. When the
# archive no longer carries any kernel under the ceiling, this exits 1 with
# that reason rather than publishing a driverless image. trixie (6.12) is
# under every ceiling, so flounder never swaps.
#
# Test hooks (same pattern as 10-kernel-swap.sh): TUNAOS_MODULES_ROOT and
# TUNAOS_BOOT_DIR relocate the filesystem; apt-cache/apt-get come from PATH.

set -xeuo pipefail

MODULES_ROOT="${TUNAOS_MODULES_ROOT:-/usr/lib/modules}"
BOOT_DIR="${TUNAOS_BOOT_DIR:-/boot}"
KVER="${1:-}"

# Refuse an empty or malformed kernel name before it reaches the rm -rf below
# (AGENTS.md "Guard a path before you destroy it").
if [[ ! "$KVER" =~ ^[0-9]+\.[0-9]+\.[0-9]+[^/]*$ ]]; then
	echo "ERROR: expected a kernel release as \$1, got '${KVER}'" >&2
	exit 1
fi

# Highest kernel series each measured driver builds on, keyed on the full
# Debian version (epoch stripped) because Debian backports kernel fixes
# within one upstream version. Add a row only from a measured dkms build,
# never from a changelog alone.
nvidia_kernel_ceiling() {
	local upstream="${1%%-*}"
	case "$upstream" in
	550.163.01)
		if dpkg --compare-versions "$1" ge 550.163.01-6; then
			echo "7.2" # measured 2026-11-06: builds on 7.2.15+deb14-amd64
		else
			echo "7.1" # -5.1 fails on 7.2.7 (strncpy), builds on 7.1.13
		fi
		;;
	550.*) echo "7.1" ;;
	*) echo "" ;;
	esac
}

# series_le A B: true when kernel series A (major.minor) <= B.
series_le() {
	[[ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" == "$2" ]]
}

DRIVER="$(apt-cache show --no-all-versions nvidia-kernel-dkms 2>/dev/null | sed -n 's/^Version: //p' | head -1)"
if [[ -z "$DRIVER" ]]; then
	echo "ERROR: apt has no candidate for nvidia-kernel-dkms; is non-free enabled?" >&2
	exit 1
fi
DRIVER_NOEPOCH="${DRIVER#*:}"
DRIVER_UPSTREAM="${DRIVER_NOEPOCH%%-*}"
CEILING="$(nvidia_kernel_ceiling "$DRIVER_NOEPOCH")"
SERIES="$(grep -oE '^[0-9]+\.[0-9]+' <<<"$KVER")"
echo "==> image kernel ${KVER} (series ${SERIES}); nvidia-kernel-dkms ${DRIVER}; ceiling ${CEILING:-none}"

if [[ -z "$CEILING" ]] || series_le "$SERIES" "$CEILING"; then
	echo "==> no kernel hold needed"
	exit 0
fi

# Same flavour (amd64, cloud-amd64, ...) as the shipped kernel; the anchored
# pattern skips the -unsigned and -dbg packages.
FLAVOUR="${KVER##*-}"
HELD=""
while read -r cand; do
	[[ -n "$cand" ]] || continue
	series_le "$(grep -oE '^[0-9]+\.[0-9]+' <<<"$cand")" "$CEILING" || continue
	apt-cache show "linux-headers-${cand}" >/dev/null 2>&1 || continue
	HELD="$cand"
done < <(apt-cache pkgnames linux-image- |
	sed -nE "s/^linux-image-([0-9]+\.[0-9]+\.[0-9]+\+deb[0-9]+-${FLAVOUR})$/\1/p" |
	sort -V)

if [[ -z "$HELD" ]]; then
	echo "ERROR: nvidia-kernel-dkms ${DRIVER} does not build on kernel ${SERIES} (ceiling ${CEILING})," >&2
	echo "       and the archive no longer carries a linux-image-*-${FLAVOUR} at or below ${CEILING}" >&2
	echo "       with matching headers. Needs a newer Debian nvidia driver (or a measured ceiling" >&2
	echo "       row for this one); see this script's header." >&2
	exit 1
fi

echo "==> holding kernel at ${HELD}: ${KVER} is above the ${CEILING} ceiling for ${DRIVER_UPSTREAM}"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends "linux-image-${HELD}"
# Also removes linux-image-amd64/-generic, which depend on the exact ABI.
apt-get purge -y "linux-image-${KVER}"
# dracut's initramfs.img (and Containerfile.debian's vmlinuz copy) are not
# owned by the package, so the purge leaves the tree behind, and
# verify-nvidia-debian.sh requires exactly one.
rm -rf "${MODULES_ROOT:?}/${KVER}"

# sid's 7.2 kernel package ships /usr/lib/modules/<kver>/vmlinuz itself
# (tunaOS#2616); 7.1.13 does not — measured, the copy below ran — so bootc
# would find no kernel without it. /boot is the overlay RUN's tmpfs, which
# the package's own postinst has just populated.
if [[ ! -s "${MODULES_ROOT}/${HELD}/vmlinuz" ]]; then
	cp "${BOOT_DIR}/vmlinuz-${HELD}" "${MODULES_ROOT}/${HELD}/vmlinuz"
fi
test -s "${MODULES_ROOT}/${HELD}/vmlinuz"
echo "==> kernel trees now: $(ls "$MODULES_ROOT")"
