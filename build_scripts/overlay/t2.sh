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
# The COPR kernel is required for the T2 bridge/keyboard/trackpad/audio stack.
# Pin the swap to that repository so a Fedora kernel can never silently win.
dnf -y swap --from-repo="copr:copr.fedorainfracloud.org:sharpenedblade:t2linux" kernel kernel
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
