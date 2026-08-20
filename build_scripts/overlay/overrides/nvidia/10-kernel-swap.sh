#!/bin/bash
# 10-kernel-swap.sh — align the image kernel with the akmods kmod BEFORE the
# NVIDIA driver install (20-nvidia.sh) runs.
#
# WHY. 20-nvidia.sh installs kmod-nvidia-${KERNEL_VRA}-*.rpm — an exact
# kernel EVR.ARCH glob, kept deliberately strict. First contact proved the
# strictness right and the alignment missing: yellowfin's base ships
# AlmaLinux Kitten's kernel (6.12.0-250.el10) while the
# akmods-nvidia-open:centos-10 bundle carries kmods for the CentOS kernel it
# was actually built against, so the glob matched nothing and the build died
# (kde-nvidia proof run 31189433990). Hoping two independently-published
# kernels agree is not a mechanism.
#
# bluefin-lts solves this BY CONSTRUCTION: its base build erases the image
# kernel and installs the one from the akmods /kernel-rpms mount
# (build_scripts/scripts/kernel-swap.sh in the snapshot), so kmod and kernel
# can never diverge. This is that mechanism, scoped to the nvidia overlay —
# and made even tighter: /tmp/kernel-rpms here is mounted from the SAME
# akmods-nvidia-open image as the kmods (every ublue akmods image ships both
# /rpms and /kernel-rpms — akmods' Containerfile.in copies both into the
# final stage), so the kernel installed here is the one the kmod was built
# against by definition, not by tag coincidence.
#
# Numbered 10- so run_buildscripts_for's human-numeric sort runs it before
# 20-nvidia.sh.

set -xeuo pipefail

# Test hooks (same pattern as TUNAOS_NVIDIA_VERIFY_ROOT in verify-nvidia.sh):
# the mount points are parameters so bats can run the real logic against
# fixture directories with rpm/dnf/curl/uname stubbed on PATH.
AKMODS_DIR="${TUNAOS_AKMODS_DIR:-/tmp/akmods-nvidia-open-rpms}"
KERNEL_RPMS_DIR="${TUNAOS_KERNEL_RPMS_DIR:-/tmp/kernel-rpms}"
MODULES_ROOT="${TUNAOS_MODULES_ROOT:-/usr/lib/modules}"

# x86_64 only, as a belt behind the build-config platform gate: the akmods
# kmods are x86_64 builds, so an arm64 or x86_64_v2 overlay could only ship
# a mislabeled driverless image — the exact bug this layer exists to end.
# bluefin scopes its GDX the same way (x86_64-only overrides/publishing).
if [[ "$(uname -m)" != "x86_64" ]]; then
	echo "ERROR: the NVIDIA overlay only supports x86_64 (akmods kmods are x86_64" >&2
	echo "       builds; kernel ARCH on this platform can never match them)." >&2
	echo "       Remove this platform from the *-nvidia flavor in" >&2
	echo "       .github/build-config.yml instead of building a driverless image." >&2
	exit 1
fi

# Diagnostic FIRST, unconditionally: when the next mismatch happens, the log
# must say what WAS in the bundle. The first failure's log did not, and that
# cost a diagnosis step.
echo "==> akmods bundle contents (${AKMODS_DIR}):"
find "$AKMODS_DIR" -name '*.rpm' | sort
echo "==> akmods kernel cache contents (${KERNEL_RPMS_DIR}):"
find "$KERNEL_RPMS_DIR" -name '*.rpm' | sort

KERNEL_NAME="kernel"

# The kernel the akmods bundle was built for, read from the cache the kmods
# shipped with (same detection as bluefin-lts kernel-swap.sh). The `|| true`
# is load-bearing: on an empty cache `ls` exits non-zero, pipefail makes the
# whole substitution non-zero, and `set -e` would kill the script HERE —
# before the diagnosis below could name the empty cache.
CACHED_VERSION=$(cd "$KERNEL_RPMS_DIR" && { ls kernel-[0-9]*.rpm 2>/dev/null || true; } | head -1 | sed -E 's/^kernel-//;s/\.rpm$//')
if [[ -z "$CACHED_VERSION" ]]; then
	echo "ERROR: could not detect a kernel version in ${KERNEL_RPMS_DIR} (listing above)" >&2
	exit 1
fi

INSTALLED_VERSION="$(rpm -q "$KERNEL_NAME" --queryformat '%{EVR}.%{ARCH}\n' | tail -1)"
echo "==> image kernel: ${INSTALLED_VERSION}; akmods kernel: ${CACHED_VERSION}"

if [[ "$INSTALLED_VERSION" == "$CACHED_VERSION" ]]; then
	echo "==> kernels already aligned; no swap needed"
else
	echo "==> swapping image kernel to the akmods-matched ${CACHED_VERSION}"

	# tunaOS#1823 on the EL10 surface (tunaOS#1725): on 2026-08-18 every EL10
	# *-nvidia leg died right below with sqlite error 11 — "database disk
	# image is malformed" on every INSERT of the kernel install transaction
	# (albacore run 32090745718, all five legs, 3/3 buildah attempts) — the
	# same error class bonito-rawhide hits in stage-2. The rpmdb this stage
	# inherits is a sqlite file in a LOWER overlay layer; rpm mmaps it, and
	# overlayfs copy-up under an mmap'd write is the known corruption shape.
	# Rebuilding the db first forces the whole database through copy-up into
	# THIS layer before the first write touches it. This is lib.sh's
	# rawhide_rpmdb_probe graduating per its own protocol on a stable base:
	# rebuild outcome + transaction outcome discriminate the two #1823
	# readings, and if the copy-up reading is right, it fixes the swap
	# outright. Deliberately FATAL on rebuild failure (unlike the rawhide
	# probe, which runs on green pinned builds): every cell that reaches this
	# branch is red today, and a db that cannot even rebuild at rest means
	# the transaction below was never going to succeed — fail here with the
	# discriminating signature in the log instead of 300 INSERT errors later.
	echo "==> rebuilding the inherited rpmdb before the swap (copy-up guard, tunaOS#1823/#1725)"
	# The bare rebuild was not enough — run 32143809963 answered with the
	# discriminating signature this guard was built to produce:
	#   error: failed to replace old database with new database!
	# and ZERO "malformed" lines. The rebuild reads and rewrites the db
	# fine; it dies at its final step, a directory RENAME over the dbpath —
	# which still lives in a LOWER overlay layer, and overlayfs refuses
	# cross-layer directory renames (EXDEV). The same mechanism is what
	# corrupts sqlite's writes in the plain install transaction (#1823).
	# So recreate the directory natively in the upper layer first: the
	# copy lands in the upper layer, the rm whiteouts the lower dir, and
	# the mv is then a same-device rename. Every subsequent rpm write —
	# the rebuild's replace included — is upper-layer-native.
	_rpmdb_dir="$(rpm --eval '%_dbpath' 2>/dev/null || true)"
	if [[ -n "$_rpmdb_dir" && -d "$_rpmdb_dir" ]]; then
		cp -a "$_rpmdb_dir" "${_rpmdb_dir}.tbox-copyup"
		rm -rf "$_rpmdb_dir"
		mv "${_rpmdb_dir}.tbox-copyup" "$_rpmdb_dir"
	fi
	rpm --rebuilddb
	echo "TUNAOS_RPMDB_PROBE=rebuilt-pre-swap"

	# Always remove these packages as kernel cache provides signed versions
	# (bluefin-lts kernel-swap.sh, verbatim reasoning).
	PKGS=("${KERNEL_NAME}" "${KERNEL_NAME}-core" "${KERNEL_NAME}-modules" "${KERNEL_NAME}-modules-core" "${KERNEL_NAME}-modules-extra" "${KERNEL_NAME}-uki-virt")
	for pkg in "${PKGS[@]}"; do
		rpm --erase "$pkg" --nodeps || true
	done

	# Install every core kernel piece the cache provides for this version.
	# Enumerated from the cache rather than hardcoded: the uki-virt/devel
	# split varies between kernel-cache builds, and a name the cache does not
	# carry would fail the transaction on a file that was never promised.
	RPM_FILES=()
	for pkg in "${PKGS[@]}"; do
		if [[ -f "${KERNEL_RPMS_DIR}/${pkg}-${CACHED_VERSION}.rpm" ]]; then
			RPM_FILES+=("${KERNEL_RPMS_DIR}/${pkg}-${CACHED_VERSION}.rpm")
		fi
	done
	if [[ "${#RPM_FILES[@]}" -eq 0 ]]; then
		echo "ERROR: no installable kernel rpms for ${CACHED_VERSION} in ${KERNEL_RPMS_DIR}" >&2
		exit 1
	fi
	# Install the cached kernel set directly with rpm, bypassing dnf's
	# exclude filtering entirely. dnf's `--setopt=exclude=` only clears the
	# [main] exclude from dnf.conf; repo-level `exclude=kernel*` in the base
	# image's .repo files still filters @commandline packages — the
	# 08-11 builds failed with "filtered out by exclude filtering" even
	# with the setopt in place (bonito 31454139305, every *-nvidia job,
	# 3/3 buildah attempts). The kernel cache carries the complete set
	# (kernel, -core, -modules, -modules-core, -modules-extra, -uki-virt)
	# so intra-set Requires resolve inside the transaction and the base
	# image supplies the rest (dracut, kmod, linux-firmware). The old
	# kernels were already erased with rpm --erase --nodeps above, so the
	# -i install has no version conflicts.
	#
	# --nosignature is required, not optional, on bonito-rawhide
	# (base_image quay.io/fedora/fedora-bootc:rawhide). The akmods kernel
	# cache RPMs are not GPG-signed by ublue-os's akmods build for ANY
	# consumer -- bonito installs the identical unsigned set from the
	# identical coreos-stable akmods bundle without incident (its failure
	# in the SAME run window was purely the unrelated sed bug one script
	# later, in 20-nvidia.sh -- proof this step passed for it). What
	# differs on rawhide is the base image's own rpm signature-verify
	# policy, which fedora-bootc:rawhide sets stricter than bonito's base:
	#
	#   package kernel-modules-core-7.1.4-100.fc43.x86_64 does not
	#   verify: no signature
	#
	# on all six kernel packages uniformly (run 31663771496,
	# bonito-rawhide gnome-nvidia) -- a property of the bundle, not
	# corruption of a subset. The actual trust boundary for this content
	# is already the pinned OCI digest of the akmods_nvidia_open build
	# stage (Containerfile.overlay); the GPG check on top of that is
	# redundant for a source that was never signed to begin with, and
	# failing on its absence here blocks every *-nvidia flavor of the one
	# variant that runs on a base image strict enough to enforce it.
	# The kernel RPM's %posttrans runs rpm-ostree kernel-install, which invokes
	# dracut before this script's explicit rebuild below. /boot is a tmpfs mount
	# in Containerfile.overlay; keep dracut's temporary output on that same
	# filesystem so its final rename cannot fail with EXDEV (Invalid cross-device
	# link) when a newer kernel package is installed.
	TMPDIR=/boot rpm -ivh --nosignature "${RPM_FILES[@]}"

	# Remove the OLD kernel's module directory outright. `rpm --erase` above
	# removes only rpm-OWNED files; generated ones (initramfs.img, depmod
	# output) are unowned, so /usr/lib/modules/<old-ver> survives as a husk —
	# and later scriptlets from the driver install cheerfully repopulate its
	# metadata. That husk is what broke the yellowfin:kde-nvidia live ISO
	# (run 31208526159): with TWO module dirs present, the ISO build resolved
	# its kernel version against the stale one, generated an initrd from a
	# tree holding no drivers at all, and paired it with the new kernel — the
	# serial showed the swapped kernel booting, tacklebox hooks present in
	# the initrd, and no sr0/cdrom ever appearing. Measured on the published
	# images: the parent ships ONE modules dir whose initramfs carries
	# sr_mod/cdrom/isofs/virtio_scsi (705 modules); the nvidia image's own
	# 6.12.0-254 initramfs carries the same set plus nvidia (720 modules) —
	# the delta was never the dracut rebuild, only the stale
	# 6.12.0-250 husk (no vmlinuz, no initramfs, empty modules.dep) sitting
	# beside it. verify-nvidia.sh now fails the build if more than one
	# module tree survives to the end.
	#
	# Only kernel-release-named entries (uname -r: <maj>.<min>.<patch>…) are
	# kernel trees. /usr/lib/modules also holds kernel-abi-stablelists'
	# rpm-owned kabi-current symlink and kabi-rhel10* directories (#1118);
	# rm -rf'ing those deletes files an installed package still owns and
	# removes nothing a kernel selector could ever pick.
	for _mod_dir in "${MODULES_ROOT}"/*/; do
		[[ -d "$_mod_dir" ]] || continue
		_mod_ver="$(basename "$_mod_dir")"
		if [[ ! "$_mod_ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
			echo "==> keeping non-kernel /usr/lib/modules entry ${_mod_ver}"
			continue
		fi
		if [[ "$_mod_ver" != "$CACHED_VERSION" ]]; then
			echo "==> removing stale kernel module tree ${_mod_dir}"
			rm -rf "$_mod_dir"
		fi
	done
fi

# Lock what we just aligned — a later transaction pulling a different kernel
# would silently undo the whole point of this script.
dnf versionlock add \
	"$KERNEL_NAME" \
	"$KERNEL_NAME"-core \
	"$KERNEL_NAME"-modules \
	"$KERNEL_NAME"-modules-core \
	"$KERNEL_NAME"-modules-extra 2>/dev/null || true

# akmods secureboot key, so the signed kmod/kernel verify on SB machines
# (bluefin-lts kernel-swap.sh does the same). Path is a test hook like the
# mounts above.
CERTS_DIR="${TUNAOS_AKMODS_CERT_DIR:-/etc/pki/akmods/certs}"
mkdir -p "$CERTS_DIR"
curl --retry 3 -fsSLo "${CERTS_DIR}/akmods-ublue.der" \
	"https://github.com/ublue-os/akmods/raw/main/certs/public_key.der"
