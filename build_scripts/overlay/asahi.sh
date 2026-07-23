#!/usr/bin/env bash
# asahi.sh — Apple Silicon (M1/M2) overlay: 16K-page Asahi kernel + platform
# userspace on top of a DE image. aarch64 only. Family-dispatched:
#
#   fedora (bonito)    — @asahi COPRs, same package set as Fedora Asahi Remix /
#                        the fedora-asahi-remix-atomic-desktops images. Most
#                        mature path.
#   EL10 family        — CentOS Hyperscale SIG packages-asahi repo (skipjack,
#                        yellowfin, albacore, redfin — centos/almalinux/rhel
#                        IDs all take this branch). The SIG repo lags upstream
#                        (~6.16 era) and lacks m1n1/u-boot/audio packages;
#                        EXPERIMENTAL, expect loud warnings.
#   arch (marlin)      — community Asahi-ALARM repo. Requires an Arch Linux ARM
#                        base (Arch proper is x86_64-only); EXPERIMENTAL.
#   debian (flounder)  — official Bananas-team userspace from the Debian
#                        archive (trixie+); kernel + mesa from the team's side
#                        archive. EXPERIMENTAL.
#   opensuse (sailfin) — no maintained Asahi packaging exists; explicit error
#                        with pointers (greenfield).
#   gentoo (guppy)     — chadmed's asahi overlay is excellent but source-based;
#                        needs binhost infra before an image build makes sense.
#                        Explicit error with pointers.
#
# What every path must deliver (see the asahi-verify 35-point harness):
#   16K asahi kernel + Apple DTBs, m1n1 + U-Boot payloads, update-m1n1,
#   ESP vendor-firmware extraction wired into the initramfs, audio stack
#   (speakers stay disabled if any audio piece is missing).
set -xeuo pipefail

if [ "$(uname -m)" != "aarch64" ]; then
	echo "ERROR: the asahi overlay only applies to aarch64 builds" >&2
	exit 1
fi

. /etc/os-release

install_best_effort() {
	# $1 = install command prefix (e.g. "dnf -y install"), rest = packages.
	local cmd="$1"
	shift
	for pkg in "$@"; do
		$cmd "$pkg" || echo "WARNING: asahi package unavailable on ${ID}: $pkg"
	done
}

# EL rebuilds (AlmaLinux, RHEL) ride the CentOS Hyperscale SIG branch.
case "${ID}" in
almalinux | rhel) ID=centos ;;
esac

case "${ID}" in
fedora)
	printf "::group:: === Asahi (Fedora) ===\n"
	# Same repo bootstrap the unofficial Asahi atomic images use: enable the
	# branding COPR for the GPG keys, then asahi-repos lays down the full set.
	dnf -y copr enable @asahi/fedora-remix-branding
	dnf -y install asahi-repos
	# Swap the stock 4K kernel for the 16K asahi build.
	dnf -y remove --no-autoremove kernel kernel-core kernel-modules \
		kernel-modules-core kernel-modules-extra || true
	dnf -y install kernel-16k kernel-16k-modules-extra \
		asahi-platform-metapackage \
		alsa-ucm-asahi tiny-dfr \
		grub2-efi-aa64-modules uboot-images-armv8 \
		asahi-fwupdate dracut-asahi update-m1n1
	;;
centos)
	printf "::group:: === Asahi (CentOS Hyperscale SIG) — EXPERIMENTAL ===\n"
	KEY=/etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-SIG-HyperScale
	if [ ! -f "$KEY" ]; then
		curl -fsSL "https://www.centos.org/keys/RPM-GPG-KEY-CentOS-SIG-HyperScale" -o "$KEY"
	fi
	for repo in packages-main packages-asahi; do
		cat >"/etc/yum.repos.d/hyperscale-${repo}.repo" <<-EOF
			[hyperscale-${repo}]
			name=CentOS Hyperscale SIG - ${repo}
			baseurl=https://mirror.stream.centos.org/SIGs/10-stream/hyperscale/\$basearch/${repo}/
			enabled=1
			gpgcheck=1
			gpgkey=file://${KEY}
		EOF
	done
	dnf -y remove --no-autoremove kernel kernel-core kernel-modules \
		kernel-modules-core kernel-modules-extra || true
	# The SIG builds 16k asahi kernel flavors + the dracut/update-m1n1 glue.
	dnf -y install kernel-16k dracut-asahi update-m1n1
	install_best_effort "dnf -y install" \
		asahi-platform-metapackage-core asahi-fwupdate asahi-scripts \
		linux-firmware-vendor asahi-battery
	echo "WARNING: the Hyperscale SIG asahi repo has no m1n1/u-boot-asahi/asahi-audio" \
		"packages as of 2026-07 — boot payloads and audio need another source" \
		"before this image can run on hardware."
	;;
arch | archarm)
	printf "::group:: === Asahi (Asahi-ALARM) — EXPERIMENTAL ===\n"
	# Requires an Arch Linux ARM base image; marlin's default base
	# (docker.io/archlinux) is x86_64-only and never reaches this branch
	# (aarch64 guard above).
	cat >/etc/pacman.d/mirrorlist.asahi-alarm <<-'EOF'
		Server = https://github.com/asahi-alarm/asahi-alarm/releases/download/$arch
	EOF
	if ! grep -q '^\[asahi-alarm\]' /etc/pacman.conf; then
		sed -i -e '/\[core\]/i [asahi-alarm]\nInclude = /etc/pacman.d/mirrorlist.asahi-alarm\n' /etc/pacman.conf
	fi
	pacman-key --init
	pacman-key --populate || true
	# Bootstrap the asahi-alarm keyring, then rely on normal sig checking.
	sed -i -e '/^\[asahi-alarm\]/a SigLevel = Optional TrustAll' /etc/pacman.conf
	pacman -Sy --noconfirm asahi-alarm-keyring ||
		echo "WARNING: asahi-alarm-keyring unavailable — repo stays at SigLevel Optional"
	pacman-key --populate asahi-alarm || true
	sed -i -e '/^SigLevel = Optional TrustAll$/d' /etc/pacman.conf
	pacman -Syu --noconfirm --needed linux-asahi asahi-scripts
	install_best_effort "pacman -S --noconfirm --needed" \
		m1n1 uboot-asahi asahi-audio alsa-ucm-conf-asahi \
		speakersafetyd tiny-dfr asahi-fwextract
	mkinitcpio -P
	pacman -Scc --noconfirm || true
	;;
debian)
	printf "::group:: === Asahi (Debian Bananas) — EXPERIMENTAL ===\n"
	# Userspace (m1n1, u-boot-asahi, asahi-scripts, audio) is official in the
	# Debian archive from trixie on; kernel + (pre-forky) mesa come from the
	# Bananas team's side archive, which ships ready-made keyring + sources.
	apt-get update -y
	apt-get install -y --no-install-recommends curl ca-certificates
	BANANAS=https://bananas-archive.debian.net/bananas-archive
	curl -fsSL "${BANANAS}/bananas-archive-keyring.gpg" \
		-o /usr/share/keyrings/bananas-archive-keyring.gpg
	SUITE=trixie
	grep -q sid /etc/debian_version 2>/dev/null && SUITE=unstable
	curl -fsSL "${BANANAS}/bananas-${SUITE}.sources" -o /etc/apt/sources.list.d/bananas.sources
	curl -fsSL "${BANANAS}/bananas-${SUITE}.pref" -o /etc/apt/preferences.d/bananas.pref || true
	apt-get update -y
	KERNEL_PKG=$(apt-cache search --names-only 'linux-image.*asahi' | awk '{print $1}' | sort -V | tail -1)
	if [ -z "$KERNEL_PKG" ]; then
		echo "ERROR: no linux-image-*asahi package found in the Bananas archive" >&2
		exit 1
	fi
	apt-get -o Dpkg::Options::="--force-confold" install -y --no-install-recommends \
		"${KERNEL_PKG}"
	install_best_effort "apt-get install -y --no-install-recommends" \
		m1n1 u-boot-asahi asahi-scripts asahi-fwextract asahi-audio \
		alsa-ucm-conf-asahi speakersafetyd tiny-dfr asahi-nvram
	apt-get clean -y && rm -rf /var/lib/apt/lists/*
	;;
opensuse* | *suse*)
	echo "ERROR: sailfin has no maintained Asahi packaging to build on" >&2
	echo "  (no OBS project exists; nearest prior art is the semi-abandoned" >&2
	echo "  github.com/mrkcee/asahi-opensuse). This path is greenfield —" >&2
	echo "  packaging must be created before an image can." >&2
	exit 1
	;;
gentoo)
	echo "ERROR: guppy asahi needs binhost infrastructure first" >&2
	echo "  chadmed's overlay (github.com/chadmed/asahi-overlay, maintained by" >&2
	echo "  an Asahi core dev) has everything, but it is source-based: an image" >&2
	echo "  build would compile the kernel + stack per build. Stand up an" >&2
	echo "  aarch64 binhost publishing overlay binpkgs, then add this branch." >&2
	exit 1
	;;
*)
	echo "ERROR: no asahi path for distro '${ID}'" >&2
	exit 1
	;;
esac

# ── Common verification + staging (dracut families; Arch uses mkinitcpio) ────
if [ "${ID}" != "arch" ] && [ "${ID}" != "archarm" ]; then
	KVER=$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1 | xargs basename)
	case "$KVER" in
	*asahi* | *16k*) ;;
	*)
		echo "ERROR: newest kernel '${KVER}' is not an asahi/16k build" >&2
		exit 1
		;;
	esac
	# Stage vmlinuz where bootc expects it (Fedora/EL RPMs do this natively;
	# Debian kernels put it in /boot).
	[ -f "/usr/lib/modules/${KVER}/vmlinuz" ] ||
		cp "/boot/vmlinuz-${KVER}" "/usr/lib/modules/${KVER}/vmlinuz"
	# Debian-family kernels ship DTBs under /usr/lib/linux-image-<kver>/;
	# stage the Apple ones at the layout update-m1n1 harvests.
	if [ ! -d "/usr/lib/modules/${KVER}/dtb/apple" ] && [ -d "/usr/lib/linux-image-${KVER}/apple" ]; then
		mkdir -p "/usr/lib/modules/${KVER}/dtb"
		cp -r "/usr/lib/linux-image-${KVER}/apple" "/usr/lib/modules/${KVER}/dtb/"
	fi
	# Debian/Ubuntu asahi-scripts packaging may target initramfs-tools; vendor
	# the upstream dracut modules if absent (all TunaOS images build their
	# initramfs with dracut).
	ASAHI_SCRIPTS_REF=b6f72e6c03550a6dab391cd7bc1bcb854fc5bacb
	if [ ! -d /usr/lib/dracut/modules.d/99asahi-firmware ]; then
		echo "vendoring asahi dracut modules from AsahiLinux/asahi-scripts@${ASAHI_SCRIPTS_REF}"
		curl -fsSL "https://github.com/AsahiLinux/asahi-scripts/archive/${ASAHI_SCRIPTS_REF}.tar.gz" | tar -xz -C /tmp
		SRC="/tmp/asahi-scripts-${ASAHI_SCRIPTS_REF}/dracut"
		mkdir -p /usr/lib/dracut/modules.d /usr/lib/dracut/dracut.conf.d
		cp -r "${SRC}/modules.d/91kernel-modules-asahi" "${SRC}/modules.d/99asahi-firmware" /usr/lib/dracut/modules.d/
		cp "${SRC}/dracut.conf.d/"*.conf /usr/lib/dracut/dracut.conf.d/ 2>/dev/null || true
		rm -rf "/tmp/asahi-scripts-${ASAHI_SCRIPTS_REF}"
	fi
	if ! grep -rqs "asahi-firmware" /usr/lib/dracut/dracut.conf.d/ /etc/dracut.conf.d/ 2>/dev/null; then
		printf 'add_dracutmodules+=" asahi-firmware kernel-modules-asahi "\n' \
			> /usr/lib/dracut/dracut.conf.d/10-asahi.conf
	fi
	# (Re)build the initramfs with the asahi modules in scope — package
	# postinst hooks do not reliably run dracut in container builds, and the
	# ESP vendor-firmware flow silently dies without these modules.
	dracut --force --no-hostonly --reproducible \
		--kver "${KVER}" "/usr/lib/modules/${KVER}/initramfs.img"
	command -v dnf >/dev/null 2>&1 && dnf clean all || true
fi

printf "::endgroup::\n"
