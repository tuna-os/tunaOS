#!/usr/bin/env bash
# t2.sh — Fedora T2 Mac hardware overlay for x86_64 bootc images.
#
# The T2 Linux project maintains the kernel and userspace packages in its COPR.
# Broadcom firmware is intentionally absent: Apple does not permit redistribution.
# Bootsahi Legacy transfers a locally extracted payload during installation.
set -xeuo pipefail

if [ "$(uname -m)" != "x86_64" ]; then
	echo "ERROR: the T2 overlay only applies to x86_64 builds" >&2
	exit 1
fi

. /etc/os-release
if [ "${ID}" != "fedora" ]; then
	echo "ERROR: the initial T2 profile is supported only on Fedora (bonito)" >&2
	exit 1
fi

dnf -y copr enable sharpenedblade/t2linux

# The COPR kernel is required for the T2 bridge/keyboard/trackpad/audio stack,
# and a Fedora kernel must never silently win. That guarantee used to be a
# `--from-repo` pin on a single swap:
#
#   dnf -y swap --from-repo="copr:…:sharpenedblade:t2linux" kernel kernel
#
# which fails every build:
#
#   Failed to resolve the transaction:
#   No match for argument 'kernel' in repositories 'copr:…:sharpenedblade:t2linux'
#
# `--from-repo` constrains BOTH specs of a swap, and the REMOVE spec is the
# INSTALLED kernel, which did not come from the COPR — so it matches nothing
# and the transaction dies before the install side is considered. The install
# side was never the problem: the enabled chroot is fedora-44 (VERSION_ID=44 in
# the build log) and that chroot carries kernel-7.1.9-200.t2.fc44, verified
# against the live repo rather than assumed. Three attempts, every run
# (bonito:gnome-t2, runs 34613732493 and 34750383558).
#
# So: remove unconstrained, install constrained, then ASSERT the result. The
# shape is asahi.sh's, which swaps a kernel the same way and for the same
# reason, and the assert is the actual guarantee — a flag whose scope surprised
# us is not one.
#
# `rpm -qa kernel*` first, so if an assumption here is wrong the log says which
# packages were actually installed rather than only "No match for argument".
echo "== kernel packages before the swap =="
rpm -qa 'kernel*' | sort

dnf -y remove --noautoremove kernel kernel-core kernel-modules \
	kernel-modules-core || true
dnf -y install --allowerasing \
	--from-repo="copr:copr.fedorainfracloud.org:sharpenedblade:t2linux" \
	kernel kernel-core kernel-modules kernel-modules-core

# The guarantee, asserted rather than assumed. `.t2.` is the COPR's dist tag.
_t2_kver="$(rpm -q kernel --qf '%{VERSION}-%{RELEASE}\n' | tail -1)"
case "${_t2_kver}" in
*.t2.*) echo "t2.sh: kernel ${_t2_kver} is the t2linux build" ;;
*)
	echo "ERROR: installed kernel is not the t2linux build: ${_t2_kver}" >&2
	exit 1
	;;
esac
dnf -y install t2linux-release iwd

install -d /etc/NetworkManager/conf.d
cat >/etc/NetworkManager/conf.d/10-t2-wifi.conf <<'EOF'
[device]
wifi.backend=iwd
EOF

# Do not install broadcom-wl: T2 Macs use the in-kernel brcmfmac driver plus
# firmware extracted locally by Bootsahi Legacy.
if rpm -q broadcom-wl >/dev/null 2>&1; then
	echo "ERROR: broadcom-wl must not be present in a T2 image" >&2
	exit 1
fi

# Keep the image publishable only when the T2 metapackage and the in-tree Wi-Fi
# driver are actually present in the selected kernel.
rpm -q t2linux-release
KVER=$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d -printf '%T@ %f\n' | sort -rn | head -1 | cut -d' ' -f2-)
[ -n "${KVER}" ] && [ -d "/usr/lib/modules/${KVER}" ] || {
	echo "ERROR: no T2 kernel module directory found" >&2
	exit 1
}
find "/usr/lib/modules/${KVER}" -type f -name 'brcmfmac.ko*' -print -quit | grep -q .
