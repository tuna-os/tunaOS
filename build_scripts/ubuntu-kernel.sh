#!/usr/bin/env bash
# Kernel + firmware install for grouper (Ubuntu). Two paths:
#
#   default          — generic kernel + linux-firmware (all arches). linux-generic
#                      unless its kernel cannot mount a composefs image from a
#                      file, in which case the release's HWE kernel — see
#                      select_kernel_pkg() for why that is a correctness
#                      requirement and not a hardware preference.
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

# Overridable so the selection below can be exercised in a tree the test owns.
# APT_LISTS_DIR matters as much as the other two: the cleanup at the end of the
# generic path is `rm -rf "${APT_LISTS_DIR}"/*`, and rm exits non-zero on
# permission denied. Under `set -e` that made every success-path test fail on
# the GitHub runner, where tests run unprivileged, while passing anywhere the
# suite happened to run as root — and there it deleted the host's apt lists.
MODULES_DIR="${MODULES_DIR:-/usr/lib/modules}"
BOOT_DIR="${BOOT_DIR:-/boot}"
APT_LISTS_DIR="${APT_LISTS_DIR:-/var/lib/apt/lists}"

# CONFIG_EROFS_FS_BACKED_BY_FILE landed in Linux 6.12. Only consulted when the
# archive publishes no .config for a kernel (see kernel_can_mount_composefs).
EROFS_FILE_BACKED_SINCE="6.12"

# stderr, not stdout: select_kernel_pkg's answer is read by the caller through a
# command substitution, and a log line on stdout becomes part of the package
# name apt is then asked to install.
log() { echo "ubuntu-kernel: $*" >&2; }

# The kernel version a meta-package would pull in, without installing it.
kernel_pkg_kver() {
	apt-get install -s -y --no-install-recommends "$1" 2>/dev/null |
		sed -n 's/^Inst linux-image-\([0-9][^ ]*\) .*/\1/p' | head -1
}

# 0 = this kernel's .config has CONFIG_EROFS_FS_BACKED_BY_FILE, 1 = it does not,
# 2 = the archive publishes no .config for it (no linux-buildinfo on this arch).
kernel_config_has_file_backed_erofs() {
	local kver="$1" dir config rc=1
	dir="$(mktemp -d)"
	# linux-buildinfo ships only the .config (~600 KB) — the same package the
	# asahi path below uses to prove CONFIG_ARM64_16K_PAGES.
	if ! (cd "$dir" && apt-get download -y "linux-buildinfo-${kver}" >/dev/null 2>&1); then
		rm -rf "$dir"
		return 2
	fi
	dpkg-deb -x "$dir"/linux-buildinfo-*.deb "${dir}/x"
	config="$(find "${dir}/x" -type f -name config | head -1)"
	if [ -z "$config" ]; then
		rm -rf "$dir"
		return 2
	fi
	grep -q '^CONFIG_EROFS_FS_BACKED_BY_FILE=y$' "$config" && rc=0
	rm -rf "$dir"
	return "$rc"
}

# Can this kernel mount the composefs image bootc installs? Asks the shipped
# .config, and only falls back to a version comparison when there is none.
kernel_can_mount_composefs() {
	local kver="$1" rc=0
	kernel_config_has_file_backed_erofs "$kver" || rc=$?
	case "$rc" in
	0) return 0 ;;
	1) return 1 ;;
	esac
	log "no linux-buildinfo-${kver} to read; comparing ${kver} against ${EROFS_FILE_BACKED_SINCE}"
	dpkg --compare-versions "${kver%%-*}" ge "$EROFS_FILE_BACKED_SINCE"
}

# Which kernel meta-package to install.
#
# THIS IS NOT A HARDWARE-ENABLEMENT PREFERENCE. Our images are composefs-native
# (prepare-root.conf sets [composefs] enabled), and bootc mounts the composefs
# image by handing EROFS an open file: `source=/proc/self/fd/<n>`. That is a
# file-backed mount, CONFIG_EROFS_FS_BACKED_BY_FILE, Linux 6.12+. A kernel
# without it has no way to mount an image that is not a block device, so EROFS
# falls through to get_tree_bdev and the install dies:
#
#   e /proc/self/fd/19: Can't lookup blockdev
#   error: Installing to filesystem: Setting up composefs boot: Failed to mount
#          composefs image: ... Creating filesystem mount: Block device
#          required (os error 15)
#
# (gurnard:pantheon, LUKS run 31071830439 — after 12 minutes of ISO build and a
# fully partitioned, LUKS-formatted disk.) The releases this file serves differ
# on exactly this symbol:
#
#   resolute (26.04, grouper)  GA 7.0.0   CONFIG_EROFS_FS_BACKED_BY_FILE=y
#   noble    (24.04, gurnard)  GA 6.8.0   absent — HWE 7.0.0 has it
#
# so the choice is made by reading the config of the kernel we are about to
# install, not by branching on a release name and not by a version table that
# goes stale the next time either release moves.
select_kernel_pkg() {
	local ga_pkg="linux-generic" ga_kver hwe_pkg hwe_kver
	ga_kver="$(kernel_pkg_kver "$ga_pkg")"
	[ -n "$ga_kver" ] || {
		echo "ERROR: apt offers no ${ga_pkg} to install" >&2
		exit 1
	}
	if kernel_can_mount_composefs "$ga_kver"; then
		echo "$ga_pkg"
		return 0
	fi

	# The HWE meta-package name comes from the archive rather than from
	# /etc/os-release, whose VERSION_ID and VERSION_CODENAME 90-image-info.sh
	# rebrands (that rebranding is what broke add-apt-repository in #1014).
	hwe_pkg="$(apt-cache search --names-only '^linux-generic-hwe-[0-9]+\.[0-9]+$' |
		awk '{print $1}' | sort -V | tail -1)"
	if [ -n "$hwe_pkg" ]; then
		hwe_kver="$(kernel_pkg_kver "$hwe_pkg")"
		if [ -n "$hwe_kver" ] && kernel_can_mount_composefs "$hwe_kver"; then
			log "${ga_pkg} (${ga_kver}) cannot mount a composefs image from a file; using ${hwe_pkg} (${hwe_kver})"
			echo "$hwe_pkg"
			return 0
		fi
	fi

	echo "ERROR: no kernel available to this base can mount a composefs image" >&2
	echo "       from a file: ${ga_pkg} gives ${ga_kver}${hwe_kver:+ and ${hwe_pkg} gives ${hwe_kver}}," >&2
	echo "       none with CONFIG_EROFS_FS_BACKED_BY_FILE (Linux ${EROFS_FILE_BACKED_SINCE}+)." >&2
	echo "       bootc's composefs backend needs it; failing here rather than" >&2
	echo "       shipping an image whose install dies in a QEMU guest." >&2
	exit 1
}

apt-get update -y

if [ "${ENABLE_ASAHI:-0}" != "1" ]; then
	KERNEL_PKG="$(select_kernel_pkg)"
	apt-get -o Dpkg::Options::="--force-confold" install -y --no-install-recommends \
		"$KERNEL_PKG" linux-firmware
	KVER=$(find "$MODULES_DIR" -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1 | xargs basename)
	cp "${BOOT_DIR}/vmlinuz-${KVER}" "${MODULES_DIR}/${KVER}/vmlinuz"
	apt-get clean -y && rm -rf "${APT_LISTS_DIR}"/*
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
curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${PPA_FPR}" |
	gpg --dearmor -o /usr/share/keyrings/ubuntu-asahi.gpg
. /etc/os-release
echo "deb [signed-by=/usr/share/keyrings/ubuntu-asahi.gpg] https://ppa.launchpadcontent.net/ubuntu-asahi/ubuntu-asahi/ubuntu ${VERSION_CODENAME} main" \
	>/etc/apt/sources.list.d/ubuntu-asahi.list
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
	apt-get install -y --no-install-recommends "$pkg" ||
		echo "WARNING: optional asahi package unavailable: $pkg"
done

KVER=$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1 | xargs basename)
case "$KVER" in
*asahi*) ;;
*)
	echo "ERROR: newest kernel '${KVER}' is not an asahi kernel" >&2
	exit 1
	;;
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
ls "/usr/lib/modules/${KVER}/dtb/apple/" >/dev/null 2>&1 ||
	echo "WARNING: no apple DTBs staged — checked firmware/device-tree and linux-image layouts for ${KVER}"

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
		>/usr/lib/dracut/dracut.conf.d/10-asahi.conf
fi

# boot.bin lifecycle on bootc (update-m1n1 scriptlets never re-run on
# deploys) — tunaOS#779.
"$(dirname "$0")/asahi/install-bootbin-sync.sh"

apt-get clean -y && rm -rf "${APT_LISTS_DIR}"/*
