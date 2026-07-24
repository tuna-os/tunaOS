#!/usr/bin/env bash
# Kernel + firmware install for grouper (Ubuntu). Two paths:
#
#   default          — stock linux-generic + linux-firmware (all arches)
#   ENABLE_ASAHI=1   — Apple Silicon (M1/M2) support from the UbuntuAsahi PPA:
#                      16K-page asahi kernel, m1n1 + U-Boot payloads,
#                      update-m1n1, ESP firmware extraction, audio DSP stack.
#                      arm64 only. https://ubuntuasahi.org
#
# Both paths stage vmlinuz into /usr/lib/modules/<kver>/ where bootc expects
# it. The asahi path also stages DTBs at /usr/lib/modules/<kver>/dtb/ (the
# layout update-m1n1 harvests) and ensures the asahi dracut modules are
# present — finalize.sh builds the initramfs with dracut, and the vendor
# firmware flow (ESP firmware.cpio -> /lib/firmware/vendor tmpfs before udev)
# only works if 99asahi-firmware + 91kernel-modules-asahi are in that build.
set -xeuo pipefail

apt-get update -y

if [ "${ENABLE_ASAHI:-0}" != "1" ]; then
    apt-get -o Dpkg::Options::="--force-confold" install -y --no-install-recommends \
        linux-generic linux-firmware
    KVER=$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1 | xargs basename)
    cp "/boot/vmlinuz-${KVER}" "/usr/lib/modules/${KVER}/vmlinuz"
    apt-get clean -y && rm -rf /var/lib/apt/lists/*
    exit 0
fi

# ─── Asahi path ──────────────────────────────────────────────────────────────
if [ "$(dpkg --print-architecture)" != "arm64" ]; then
    echo "ERROR: ENABLE_ASAHI=1 requires an arm64 build" >&2
    exit 1
fi

apt-get install -y --no-install-recommends curl ca-certificates gpg jq

# UbuntuAsahi PPA. The signing-key fingerprint comes from the Launchpad API so
# it tracks key rotations instead of being baked in stale.
PPA_FPR=$(curl -fsSL "https://api.launchpad.net/1.0/~ubuntu-asahi/+archive/ubuntu/ubuntu-asahi" | jq -r .signing_key_fingerprint)
curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${PPA_FPR}" \
    | gpg --dearmor -o /usr/share/keyrings/ubuntu-asahi.gpg
. /etc/os-release
echo "deb [signed-by=/usr/share/keyrings/ubuntu-asahi.gpg] https://ppa.launchpadcontent.net/ubuntu-asahi/ubuntu-asahi/ubuntu ${VERSION_CODENAME} main" \
    > /etc/apt/sources.list.d/ubuntu-asahi.list
apt-get update -y

# Kernel: resolve the image package name rather than hardcoding it (the PPA
# has used linux-image-asahi / linux-image-<ver>-asahi-arm namings).
KERNEL_PKG=$(apt-cache search --names-only '^linux-image-.*asahi' | awk '{print $1}' | sort -V | tail -1)
if [ -z "$KERNEL_PKG" ]; then
    echo "ERROR: no linux-image-*asahi package found in the UbuntuAsahi PPA for ${VERSION_CODENAME}" >&2
    exit 1
fi
echo "Using asahi kernel package: ${KERNEL_PKG}"
apt-get -o Dpkg::Options::="--force-confold" install -y --no-install-recommends \
    "${KERNEL_PKG}" linux-firmware

# Platform userspace. Installed one by one: the PPA's package set has shifted
# over releases, and a missing optional piece should be a warning we read in
# the build log, not a failed image. REQUIRED failures are fatal below.
REQUIRED_PKGS=(m1n1 u-boot-asahi asahi-scripts)
OPTIONAL_PKGS=(asahi-fwextract asahi-audio alsa-ucm-conf-asahi speakersafetyd tiny-dfr asahi-nvram)
for pkg in "${REQUIRED_PKGS[@]}"; do
    apt-get install -y --no-install-recommends "$pkg"
done
for pkg in "${OPTIONAL_PKGS[@]}"; do
    apt-get install -y --no-install-recommends "$pkg" \
        || echo "WARNING: optional asahi package unavailable: $pkg"
done

KVER=$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1 | xargs basename)
case "$KVER" in
    *asahi*) ;;
    *) echo "ERROR: newest kernel '${KVER}' is not an asahi kernel" >&2; exit 1 ;;
esac
cp "/boot/vmlinuz-${KVER}" "/usr/lib/modules/${KVER}/vmlinuz"

# linux-buildinfo ships the kernel .config — the only distro-independent
# proof that this build actually has CONFIG_ARM64_16K_PAGES=y (Apple
# Silicon's DART IOMMU requires 16K pages; Ubuntu's asahi-arm version
# string doesn't encode it the way Fedora's +16k suffix does). Optional:
# don't fail the build if it's missing, the verify harness will catch it.
apt-get install -y --no-install-recommends "linux-buildinfo-${KVER}" 2>/dev/null &&
    cp "/usr/lib/linux/${KVER}/config" "/usr/lib/modules/${KVER}/config" 2>/dev/null ||
    echo "WARNING: linux-buildinfo-${KVER} unavailable — kernel config not staged"

# DTBs: Debian-family kernels ship devicetrees under /usr/lib/linux-image-<kver>/.
# Stage the Apple ones at /usr/lib/modules/<kver>/dtb/ — the layout update-m1n1
# harvests and our verify harness checks. Ubuntu kernels ship DTBs in
# linux-modules at /lib/firmware/<kver>/device-tree/ (that's also Ubuntu's
# own update-m1n1 DTBS default); Debian-style packages use
# /usr/lib/linux-image-<kver>/.
if [ ! -d "/usr/lib/modules/${KVER}/dtb/apple" ]; then
    for src in \
        "/usr/lib/firmware/${KVER}/device-tree" \
        "/lib/firmware/${KVER}/device-tree" \
        "/usr/lib/linux-image-${KVER}"; do
        if [ -d "${src}/apple" ]; then
            mkdir -p "/usr/lib/modules/${KVER}/dtb"
            cp -r "${src}/apple" "/usr/lib/modules/${KVER}/dtb/"
            break
        fi
    done
fi
ls "/usr/lib/modules/${KVER}/dtb/apple/" >/dev/null 2>&1 \
    || echo "WARNING: no apple DTBs staged — checked firmware/device-tree and linux-image layouts for ${KVER}"

# Dracut modules: finalize.sh builds the initramfs with dracut. If the deb
# packaging didn't ship the asahi dracut modules (Debian/Ubuntu default to
# initramfs-tools), vendor them from upstream asahi-scripts (pinned ref).
ASAHI_SCRIPTS_REF=b6f72e6c03550a6dab391cd7bc1bcb854fc5bacb
if [ ! -d /usr/lib/dracut/modules.d/99asahi-firmware ]; then
    echo "asahi dracut modules not shipped by packages — vendoring from AsahiLinux/asahi-scripts@${ASAHI_SCRIPTS_REF}"
    curl -fsSL "https://github.com/AsahiLinux/asahi-scripts/archive/${ASAHI_SCRIPTS_REF}.tar.gz" | tar -xz -C /tmp
    SRC="/tmp/asahi-scripts-${ASAHI_SCRIPTS_REF}/dracut"
    mkdir -p /usr/lib/dracut/modules.d /usr/lib/dracut/dracut.conf.d
    cp -r "${SRC}/modules.d/91kernel-modules-asahi" "${SRC}/modules.d/99asahi-firmware" /usr/lib/dracut/modules.d/
    cp "${SRC}/dracut.conf.d/"*.conf /usr/lib/dracut/dracut.conf.d/ 2>/dev/null || true
    rm -rf "/tmp/asahi-scripts-${ASAHI_SCRIPTS_REF}"
fi
# Make sure dracut actually includes them.
if ! grep -rqs "asahi-firmware" /usr/lib/dracut/dracut.conf.d/ /etc/dracut.conf.d/ 2>/dev/null; then
    printf 'add_dracutmodules+=" asahi-firmware kernel-modules-asahi "\n' \
        > /usr/lib/dracut/dracut.conf.d/10-asahi.conf
fi

# boot.bin lifecycle on bootc (update-m1n1 scriptlets never re-run on
# deploys) — tunaOS#779.
"$(dirname "$0")/asahi/install-bootbin-sync.sh"

apt-get clean -y && rm -rf /var/lib/apt/lists/*
