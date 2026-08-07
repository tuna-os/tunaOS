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
	dnf -y install "${RPM_FILES[@]}"
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
