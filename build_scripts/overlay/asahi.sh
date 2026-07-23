#!/usr/bin/env bash
# asahi.sh — Apple Silicon (M1/M2) overlay: 16K-page Asahi kernel + platform
# userspace on top of a DE image. aarch64 only. Family-dispatched:
#
#   fedora (bonito)    — @asahi COPRs, same package set as Fedora Asahi Remix /
#                        the fedora-asahi-remix-atomic-desktops images. Most
#                        mature path.
#   centos (skipjack)  — CentOS Hyperscale SIG packages-asahi repo. The SIG
#                        repo lags upstream (~6.16 era) and lacks m1n1/u-boot/
#                        audio packages; EXPERIMENTAL, expect loud warnings.
#   arch (marlin)      — community Asahi-ALARM repo. Requires an Arch Linux ARM
#                        base (Arch proper is x86_64-only); EXPERIMENTAL.
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
*)
	echo "ERROR: no asahi path for distro '${ID}'" >&2
	exit 1
	;;
esac

# ── Common verification + staging (rpm families; Arch handled by mkinitcpio) ──
if [ "${ID}" != "arch" ] && [ "${ID}" != "archarm" ]; then
	KVER=$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d | sort -V | tail -1 | xargs basename)
	case "$KVER" in
	*asahi* | *16k*) ;;
	*)
		echo "ERROR: newest kernel '${KVER}' is not an asahi/16k build" >&2
		exit 1
		;;
	esac
	# Fedora/EL kernel RPMs place vmlinuz in /usr/lib/modules/<kver>/ already;
	# make sure, then (re)build the initramfs with the asahi dracut modules in
	# scope — RPM %posttrans does not reliably run dracut in container builds.
	[ -f "/usr/lib/modules/${KVER}/vmlinuz" ] ||
		cp "/boot/vmlinuz-${KVER}" "/usr/lib/modules/${KVER}/vmlinuz"
	dracut --force --no-hostonly --reproducible \
		--kver "${KVER}" "/usr/lib/modules/${KVER}/initramfs.img"
	dnf clean all || true
fi

printf "::endgroup::\n"
