#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 10 Base Packages ===\n"

source /run/context/build_scripts/lib.sh

# Source RHSM credentials from the BuildKit secret if it's mounted.
# /run/secrets/rhsm is provided by the `--mount=type=secret,id=rhsm`
# directive in the Containerfile (only when RHSM_* env was set when
# the Justfile invoked podman build). The file exports RHSM_USER etc.
# into our shell so the subscription-manager calls below see them; the
# secret is gone the moment this RUN completes — no image layer or
# build-history record retains the values.
if [[ -f /run/secrets/rhsm ]]; then
	# shellcheck disable=SC1091 # path only exists at build time
	. /run/secrets/rhsm
fi

# ── apt (Ubuntu/Debian) path ──────────────────────────────────────────
if [[ "$PKG_MGR" == "apt" ]]; then
	# Base packages common to all desktop flavors on apt-based systems.
	# Package name mapping from RPM: gcc-c++ → g++, xhost → x11-xserver-utils,
	# systemd-oomd-defaults → systemd-oomd, tuned-ppd → power-profiles-daemon.
	pkg_install \
		buildah \
		podman \
		skopeo \
		systemd-container \
		util-linux \
		fdisk \
		flatpak \
		distrobox \
		fwupd \
		dbus-daemon \
		fuse-overlayfs \
		systemd-resolved \
		btrfs-progs \
		gcc \
		g++ \
		plymouth \
		plymouth-themes \
		xdg-desktop-portal \
		systemd-oomd \
		power-profiles-daemon \
		fzf \
		wl-clipboard \
		wayland-utils \
		grim \
		x11-xserver-utils \
		unzip \
		powertop \
		systemd-boot \
		just \
		ffmpeg \
		gstreamer1.0-plugins-base \
		gstreamer1.0-plugins-good \
		gstreamer1.0-plugins-bad \
		gstreamer1.0-plugins-ugly \
		gstreamer1.0-libav \
		libavcodec-extra

	# Release-dependent extras, best-effort.
	#
	# These three are in Ubuntu resolute (grouper) but NOT in noble (gurnard):
	# fastfetch landed after 24.04, and glow/gum (charmbracelet) later still.
	# apt fails the entire transaction on one unknown name, so listing them
	# above took the whole base install down with
	#
	#   E: Unable to locate package fastfetch
	#   E: Unable to locate package glow
	#   E: Unable to locate package gum
	#
	# and gurnard could not build at all (LUKS run 31059184838) — the other 40
	# packages were fine. They are conveniences (a fetch tool and two TUI
	# helpers), not part of any contract, so a release that lacks them should
	# lose them and nothing else. apt_install_available names each one it skips
	# rather than dropping them quietly.
	apt_install_available fastfetch glow gum

	# Remove unwanted packages
	# shellcheck disable=SC2015 # intentional: A&&B||true is a guard pattern
	[[ "$IS_UBUNTU" == true ]] && pkg_remove ubuntu-advantage-tools || true

	# Install uupd from GitHub release (same source as RPM path)
	UUPD_VERSION=$(grep '^\s*uupd:' /run/context/image-versions.yaml | sed 's/.*"\(.*\)".*/\1/')
	UUPD_ARCH="$(uname -m | sed 's/x86_64/x86_64/;s/aarch64/arm64/')"
	UUPD_SRC_BASE="https://raw.githubusercontent.com/ublue-os/uupd/${UUPD_VERSION}"

	# Download binary tarball (separate, so partial download doesn't corrupt)
	# and systemd units (parallel — small, safe to Z).
	curl --retry 3 --fail -sSL -o /tmp/uupd.tar.gz \
		"https://github.com/ublue-os/uupd/releases/download/${UUPD_VERSION}/uupd_Linux_${UUPD_ARCH}.tar.gz"
	tar -xzf /tmp/uupd.tar.gz -C /usr/bin uupd
	rm -f /tmp/uupd.tar.gz
	curl --retry 3 --fail -Z -s \
		-o /usr/lib/systemd/system/uupd.service "${UUPD_SRC_BASE}/uupd.service" \
		-o /usr/lib/systemd/system/uupd.timer "${UUPD_SRC_BASE}/uupd.timer" \
		-o /usr/lib/systemd/system/uupd-manual.service "${UUPD_SRC_BASE}/uupd-manual.service"

	printf "::endgroup::\n"
	return 0
fi
# ── dnf (RPM) path continues below ────────────────────────────────────

# Speed up every dnf transaction in this and all downstream RUN layers.
# max_parallel_downloads fetches packages concurrently — the single biggest
# win, since RPM downloads dominate build time on the EL10/Fedora variants.
# The setting persists in /etc/dnf/dnf.conf so 20-packages, install-desktop,
# etc. all inherit it, and it changes nothing about *what* is installed.
# (fastestmirror is deliberately not enabled — the codebase already disables
# it for epel-multimedia; the mirror probe can hurt more than it helps.)
if [[ -f /etc/dnf/dnf.conf ]] && ! grep -q '^max_parallel_downloads' /etc/dnf/dnf.conf; then
	echo 'max_parallel_downloads=10' >>/etc/dnf/dnf.conf
fi

# This thing slows down downloads A LOT for no reason
if [[ $IS_CENTOS == true ]]; then
	dnf remove -y subscription-manager
elif [[ $IS_RHEL == true ]]; then
	# Check for subscription-manager credentials and register if present
	if [[ -n "${RHSM_USER:-}" ]] && [[ -n "${RHSM_PASSWORD:-}" ]]; then
		echo "Registering with Red Hat Subscription Manager using credentials..."
		warn_on_fail subscription-manager register --username "${RHSM_USER}" --password "${RHSM_PASSWORD}"
	elif [[ -n "${RHSM_ORG:-}" ]] && [[ -n "${RHSM_ACTIVATION_KEY:-}" ]]; then
		echo "Registering with Red Hat Subscription Manager using activation key..."
		warn_on_fail subscription-manager register --org "${RHSM_ORG}" --activationkey "${RHSM_ACTIVATION_KEY}"
	fi

	# Ensure repositories are enabled after registration
	warn_on_fail subscription-manager repos --enable "rhel-10-for-x86_64-baseos-rpms"
	warn_on_fail subscription-manager repos --enable "rhel-10-for-x86_64-appstream-rpms"
fi

dnf -y install 'dnf-command(versionlock)' || true
if dnf versionlock --help >/dev/null 2>&1; then
	dnf versionlock add kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt || true
fi

if [[ $IS_HUMMINGBIRD == true ]]; then
	echo "Hummingbird base detected; using --skip-unavailable for base packages..."
	dnf -y install --skip-unavailable \
		buildah \
		podman \
		skopeo \
		systemd-container \
		btrfs-progs \
		gcc \
		gcc-c++ \
		just || true
elif [[ $IS_FEDORA == true ]]; then
	FEDORA_VER="$(rpm -E %fedora)"
	if [[ -z "${FEDORA_VER}" || "${FEDORA_VER}" == "%fedora" ]]; then
		FEDORA_VER="rawhide"
	fi
	# Install config-manager, RPM Fusion, multimedia, and common packages
	# in as few transactions as possible (each dnf invocation incurs ~10-20s
	# metadata resolution overhead).
	dnf -y install 'dnf5-command(config-manager)' || true
	dnf -y install \
		"https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-${FEDORA_VER}.noarch.rpm" \
		"https://download1.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-${FEDORA_VER}.noarch.rpm" || true

	# RPM Fusion multimedia set — its own transaction, tolerant ONLY on
	# Rawhide (tunaOS#1810). gstreamer1-plugin-libav is Fedora's own package
	# (measured in the F44 repodata); with RPM Fusion's full ffmpeg installed
	# alongside it, its libgstlibav.so resolves the full libavcodec sonames —
	# that pairing is what gives GStreamer apps H.264/H.265 decode.
	# gstreamer1-plugins-ugly is the RPM Fusion build. The build contract
	# asserts the result (verify-desktop-experience.sh codec baseline).
	# Note: On Rawhide (Fedora 46+), exclude openh264* until fedora-cisco-openh264
	# updates its openh264 RPMs signed with the F46 key (currently fc45 signed with F45 key).
	# Remove this exclude once openh264-*.fc46 appears in fedora-cisco-openh264.
	dnf_opts=()
	if [[ "${FEDORA_VER}" == "rawhide" ]]; then
		dnf_opts+=(--exclude='openh264*')
	fi
	# install_rawhide_tolerant (build_scripts/lib.sh) behaves exactly like a
	# plain `dnf -y install` on every pinned Fedora release — including this
	# one, bonito — and only degrades to a --skip-broken retry + loud
	# wishlist record when FEDORA_VER=rawhide AND the strict transaction
	# fails (e.g. rpmfusion-free-rawhide's ffmpeg-libs needing a liboapv
	# SONAME Fedora rawhide no longer ships). Kept as its own transaction,
	# separate from the required base packages below, so a rawhide codec
	# skew can never tolerate away buildah/podman/etc — those still fail the
	# build strictly on every release, rawhide included.
	install_rawhide_tolerant "${dnf_opts[@]}" \
		gstreamer1-plugins-good \
		gstreamer1-plugins-ugly \
		gstreamer1-plugin-libav \
		gstreamer1-plugins-bad-free \
		lame \
		ffmpeg

	# Common desktop + container-tooling packages — always a strict
	# transaction; a failure here fails the build on every Fedora release,
	# rawhide included. Never routed through install_rawhide_tolerant: none
	# of these are expected to be affected by the rpmfusion/rawhide skew,
	# and none of them should ever become silently optional.
	dnf -y install \
		buildah \
		podman \
		skopeo \
		systemd-container \
		flatpak \
		distrobox \
		fastfetch \
		fpaste \
		fwupd \
		systemd-resolved \
		btrfs-progs \
		gcc \
		gcc-c++ \
		plymouth \
		plymouth-system-theme \
		plymouth-plugin-script \
		xdg-desktop-portal \
		systemd-oomd-defaults \
		unzip
else
	# Enable the EPEL repos for RHEL and AlmaLinux
	# RHEL requires URL-based EPEL install since epel-release is not in default repos
	if [[ $IS_RHEL == true ]]; then
		dnf install -y "https://dl.fedoraproject.org/pub/epel/epel-release-latest-${MAJOR_VERSION_NUMBER}.noarch.rpm"
		subscription-manager repos --enable "codeready-builder-for-rhel-${MAJOR_VERSION_NUMBER}-$(uname -m)-rpms"
	else
		# Install config-manager before enabling repos — crb enable / dnf config-manager
		# require the dnf-command(config-manager) package on EL10.
		# (Fedora uses dnf5-command(config-manager); EL10 uses the legacy name.)
		dnf install -y epel-release 'dnf-command(config-manager)'
		/usr/bin/crb enable
		dnf config-manager --set-enabled crb
	fi
	dnf config-manager --set-enabled epel

	# Multimedia codecs — negativo17 epel-multimedia (same as upstream
	# bluefin-lts), on BOTH x86_64 legs.
	#
	# The v2 leg used to get `ffmpeg-free` and nothing else patent-encumbered
	# ("no epel-multimedia for x86_64_v2"), which shipped flagship images
	# that could not decode H.264/H.265 at all. The actual obstacle was only
	# the repo file's $basearch: negativo17 publishes no x86_64_v2 tree
	# (measured: .../epel-10/x86_64_v2/repodata/repomd.xml is 404 while the
	# x86_64 path is 200), so on a v2 image the baseurl resolved to a 404 and
	# skip_if_unavailable made the whole repo vanish. The v2 leg has always
	# installed plain-x86_64 payloads regardless — ffmpeg-free exists only as
	# EPEL's x86_64 build — so pin the basearch and install the same full set
	# everywhere. If the depsolver ever disagrees on v2, the build fails
	# loudly, which beats silently shipping a no-H.264 image.
	#
	# Written with curl+sed rather than `dnf config-manager` so the repo
	# state is identical text on every EL10 base and there is no dnf4/dnf5
	# syntax split to carry.
	curl --retry 3 -fsSL https://negativo17.org/repos/epel-multimedia.repo \
		-o /etc/yum.repos.d/epel-multimedia.repo
	# Disabled at rest; enabled per-transaction below (previous behavior).
	sed -i 's/^enabled=1/enabled=0/' /etc/yum.repos.d/epel-multimedia.repo
	# Disable fastestmirror for this repo to avoid corrupted mirrors
	sed -i '/^\[epel-multimedia\]$/a fastestmirror=0' /etc/yum.repos.d/epel-multimedia.repo
	if is_x86_64_v2; then
		# shellcheck disable=SC2016  # $basearch is a dnf repo variable, not a shell one
		sed -i 's|/\$basearch/|/x86_64/|' /etc/yum.repos.d/epel-multimedia.repo
	fi

	# gstreamer1-plugins-ugly and gstreamer1-plugin-libav are the two that
	# make GStreamer applications (totem, thumbnailers, anything WebKit)
	# actually decode H.264/H.265 — libgstlibav.so routes through the full
	# negativo17 libavcodec installed here. Both names measured present in
	# the epel-10 repodata. The build contract asserts the result
	# (verify-desktop-experience.sh codec baseline).
	dnf_retry -y install --enablerepo=epel-multimedia \
		ffmpeg \
		libavcodec \
		@multimedia \
		gstreamer1-plugins-bad-free \
		gstreamer1-plugins-bad-free-libs \
		gstreamer1-plugins-good \
		gstreamer1-plugins-base \
		gstreamer1-plugins-ugly \
		gstreamer1-plugin-libav \
		lame \
		lame-libs \
		libjxl \
		ffmpegthumbnailer

	if [[ $IS_ALMALINUX == true ]] && [ "$MAJOR_VERSION_NUMBER" -ge 9 ]; then
		dnf swap -y coreutils-single coreutils
	fi

	# Common desktop packages (shared between GNOME and KDE) — single
	# transaction. Pulls from EPEL (gum, distrobox, fastfetch, glow) so
	# wrapped in dnf_retry to absorb mirror flakes.
	# gcc + gcc-c++ required by Homebrew formulae that build from source.
	dnf_retry -y install \
		buildah \
		btrfs-progs \
		distrobox \
		fastfetch \
		flatpak \
		fpaste \
		fwupd \
		dbus-daemon \
		fuse-overlayfs \
		systemd-resolved \
		systemd-container \
		systemd-oomd \
		gcc \
		gcc-c++ \
		plymouth \
		plymouth-system-theme \
		plymouth-plugin-script \
		libcamera-v4l2 \
		libcamera-gstreamer \
		libcamera-tools \
		system-reinstall-bootc \
		powertop \
		tuned-ppd \
		fzf \
		glow \
		wl-clipboard \
		gum \
		xhost \
		unzip
fi

dnf -y remove console-login-helper-messages setroubleshoot || true

# Install uupd from GitHub release tarball.
# The ublue-os/packages COPR dropped epel-10 chroots (~2026-06-08);
# Bluefin LTS adopted this same approach.
# Version is pinned in image-versions.yaml and tracked by Renovate.
UUPD_VERSION=$(grep '^\s*uupd:' /run/context/image-versions.yaml | sed 's/.*"\(.*\)".*/\1/')
UUPD_ARCH="$(uname -m | sed 's/x86_64/x86_64/;s/aarch64/arm64/')"
UUPD_SRC_BASE="https://raw.githubusercontent.com/ublue-os/uupd/${UUPD_VERSION}"

# Download binary tarball (separate, so partial download doesn't corrupt)
# and systemd units (parallel — small, safe to Z).
curl --retry 3 --fail -sSL -o /tmp/uupd.tar.gz \
	"https://github.com/ublue-os/uupd/releases/download/${UUPD_VERSION}/uupd_Linux_${UUPD_ARCH}.tar.gz"
tar -xzf /tmp/uupd.tar.gz -C /usr/bin uupd
rm -f /tmp/uupd.tar.gz
curl --retry 3 --fail -Z -s \
	-o /usr/lib/systemd/system/uupd.service "${UUPD_SRC_BASE}/uupd.service" \
	-o /usr/lib/systemd/system/uupd.timer "${UUPD_SRC_BASE}/uupd.timer" \
	-o /usr/lib/systemd/system/uupd-manual.service "${UUPD_SRC_BASE}/uupd-manual.service"
printf "::endgroup::\n"
