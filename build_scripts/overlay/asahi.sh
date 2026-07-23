#!/usr/bin/env bash
# asahi.sh — Apple Silicon (M1/M2) overlay: 16K-page Asahi kernel + platform
# userspace on top of a DE image. aarch64 only. Family-dispatched:
#
#   fedora (bonito)    — @asahi COPRs, same package set as Fedora Asahi Remix /
#                        the fedora-asahi-remix-atomic-desktops images. Most
#                        mature path.
#   EL10 family        — CentOS Hyperscale SIG packages-asahi (kernel-16k,
#                        glue, metapackages) + EPEL10 (m1n1, audio stack) +
#                        @asahi/u-boot COPR (apple_m1 uboot-images-armv8).
#                        Complete stack as of 2026-07 except tiny-dfr; kernel
#                        lags upstream (6.16 era vs 7.0). skipjack, yellowfin,
#                        albacore, redfin — centos/almalinux/rhel IDs all take
#                        this branch.
#   arch (marlin)      — community Asahi-ALARM repo on the tuna-os ALARM base
#                        (ghcr.io/tuna-os/archlinuxarm, built by
#                        build-archlinuxarm-base.yml from the official rootfs
#                        tarball — #778); EXPERIMENTAL.
#   debian (flounder)  — official Bananas-team userspace from the Debian
#                        archive (trixie+); kernel + mesa from the team's side
#                        archive. EXPERIMENTAL.
#   opensuse (sailfin) — OBS home:mrkcee full stack (kernel-asahi 7.0.13,
#                        current, m1n1/u-boot/audio incl.); EXPERIMENTAL,
#                        single-maintainer home: project.
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
	printf "::group:: === Asahi (CentOS Hyperscale SIG + EPEL10 + @asahi/u-boot) ===\n"
	# Full stack, three sources (verified 2026-07-23):
	#   Hyperscale packages-asahi — kernel-16k, dracut-asahi, update-m1n1,
	#     asahi-scripts/-fwupdate/-battery, linux-firmware-vendor, metapackages
	#   EPEL10 — m1n1, asahi-audio, alsa-ucm-asahi, speakersafetyd
	#   @asahi/u-boot COPR (epel-10-aarch64) — uboot-images-armv8 with the
	#     apple_m1 payload update-m1n1 hard-requires (in no EL repo yet)
	# Still unpackaged for EL10: tiny-dfr (Touch Bar; best-effort below).
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
	# TunaOS EL10 bases enable EPEL in 10-base-packages.sh; make sure anyway
	# (m1n1 + the audio stack resolve from there).
	rpm -q epel-release >/dev/null 2>&1 || dnf -y install epel-release || true
	COPR_UBOOT="https://download.copr.fedorainfracloud.org/results/@asahi/u-boot"
	cat >/etc/yum.repos.d/asahi-u-boot-copr.repo <<-EOF
		[copr-asahi-u-boot]
		name=Copr @asahi/u-boot (apple_m1 uboot-images-armv8 for EL10)
		baseurl=${COPR_UBOOT}/epel-10-\$basearch/
		enabled=1
		gpgcheck=1
		gpgkey=${COPR_UBOOT}/pubkey.gpg
	EOF
	dnf -y remove --no-autoremove kernel kernel-core kernel-modules \
		kernel-modules-core kernel-modules-extra || true
	# metapackage-core pulls kernel-16k, dracut-asahi, update-m1n1 (-> m1n1 +
	# uboot-images-armv8), alsa-ucm-asahi, asahi-fwupdate.
	dnf -y install kernel-16k kernel-16k-modules-extra \
		asahi-platform-metapackage-core
	install_best_effort "dnf -y install" \
		asahi-platform-metapackage-audio asahi-scripts \
		linux-firmware-vendor asahi-battery tiny-dfr
	;;
arch | archarm)
	printf "::group:: === Asahi (Asahi-ALARM) — EXPERIMENTAL ===\n"
	# Runs on the tuna-os ALARM base (ghcr.io/tuna-os/archlinuxarm);
	# marlin's amd64 base (docker.io/archlinux) never reaches this branch
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
	# No mkinitcpio here: marlin images are dracut-based like every other
	# TunaOS variant; the common section below rebuilds the initramfs.
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
	printf "::group:: === Asahi (openSUSE OBS home:mrkcee) — EXPERIMENTAL ===\n"
	# OBS home:mrkcee is a real, current full-stack Asahi set for Factory ARM:
	# kernel-asahi 7.0.13 (matches Fedora Asahi), m1n1, u-boot-asahi, audio,
	# 158+ revisions, updated 2026-06. Caveat: a single-maintainer home:
	# project, not a devel project — treat as upstream-worth-adopting
	# (hardware:asahi would be the graduation path).
	zypper --non-interactive --gpg-auto-import-keys addrepo \
		"https://download.opensuse.org/repositories/home:/mrkcee/openSUSE_Factory_ARM/home:mrkcee.repo"
	zypper --non-interactive --gpg-auto-import-keys refresh
	zypper --non-interactive remove --no-confirm kernel-default || true
	zypper --non-interactive install --no-confirm --no-recommends \
		kernel-asahi m1n1 u-boot-asahi asahi-scripts
	install_best_effort "zypper --non-interactive install --no-confirm --no-recommends" \
		asahi-fwextract asahi-audio alsa-ucm-conf-asahi speakersafetyd \
		triforce-lv2 bankstown-lv2 asahi-nvram tiny-dfr
	zypper clean --all || true
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

# ── Common verification + staging (all families are dracut-based) ────────────
{
	KVER=$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1 | xargs basename)
	case "$KVER" in
	*asahi* | *16k*) ;;
	*)
		echo "ERROR: newest kernel '${KVER}' is not an asahi/16k build" >&2
		exit 1
		;;
	esac
	# Stage vmlinuz where bootc expects it (Fedora/EL RPMs do this natively;
	# Debian kernels put it in /boot; Arch names it after the package).
	if [ ! -f "/usr/lib/modules/${KVER}/vmlinuz" ]; then
		for cand in "/boot/vmlinuz-${KVER}" /boot/vmlinuz-linux-asahi /boot/Image; do
			[ -f "$cand" ] && cp "$cand" "/usr/lib/modules/${KVER}/vmlinuz" && break
		done
	fi
	[ -f "/usr/lib/modules/${KVER}/vmlinuz" ] || {
		echo "ERROR: no kernel image found for ${KVER}" >&2
		exit 1
	}
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
	# boot.bin lifecycle on bootc (update-m1n1 scriptlets never re-run on
	# deploys) — tunaOS#779.
	"$(dirname "$0")/../asahi/install-bootbin-sync.sh"

	# (Re)build the initramfs with the asahi modules in scope — package
	# postinst hooks do not reliably run dracut in container builds, and the
	# ESP vendor-firmware flow silently dies without these modules.
	dracut --force --no-hostonly --reproducible \
		--kver "${KVER}" "/usr/lib/modules/${KVER}/initramfs.img"
	command -v dnf >/dev/null 2>&1 && dnf clean all || true
}

printf "::endgroup::\n"
