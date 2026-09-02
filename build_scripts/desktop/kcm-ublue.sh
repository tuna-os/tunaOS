#!/usr/bin/env bash
# Build and install kcm_ublue, set up Bazaar Flatpak, and copy oversteer
# udev rules.
#
# Called during KDE image builds (kde.sh "base" or "extra").
# Uses pinned versions from image-versions.yaml (managed by Renovate).
#
# These packages were previously pulled from the ublue-os/packages COPR,
# which dropped EPEL/CentOS chroots (~2026-06-08).

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

rpmdb_stage2_guard

# kcm_ublue and its build tooling come from dnf/COPR. On RPM-less distros
# (openSUSE/Gentoo/Arch) skip it rather than fail with "dnf: command not found".
if ! command -v dnf &>/dev/null; then
	echo "kcm-ublue.sh: skipping (no dnf available)"
	return 0 2>/dev/null || exit 0
fi

printf "::group:: === KCM Ublue + Bazaar + Oversteer Udev ===\n"

# ---- Version pins --------------------------------------------------------
KCM_UBLUE_VERSION=$(grep '^\s*kcm_ublue:' /run/context/image-versions.yaml | sed 's/.*"\(.*\)".*/\1/')

ARCH=$(uname -m)
# GitHub release arch naming: x86_64 → x86_64, aarch64 → aarch64
RPM_ARCH="$ARCH"

# ---- kcm_ublue: build from source ----------------------------------------
echo "Building kcm_ublue ${KCM_UBLUE_VERSION} from source..."

# Install build dependencies (removed after build)
BUILD_DEPS=(
	git
	cmake
	gcc-g++
	extra-cmake-modules
	kf6-kcmutils-devel
	kf6-config-devel
	kf6-configwidgets-devel
	kf6-coreaddons-devel
	kf6-i18n-devel
	kf6-auth-devel
	kf6-codecs-devel
	kf6-colorscheme-devel
	kf6-service-devel
	kf6-widgetsaddons-devel
	qt6-qtbase-devel
	qt6-qtdeclarative-devel
	qt6-qttools-devel
	gtest-devel
)

# kcm_ublue is built from source and needs the KF6 / Qt6 *-devel headers.
# Those aren't in every EL repo set — AlmaLinux Kitten (yellowfin) ships the
# KF6 runtime but not the -devel packages, so a hard `dnf install` failed the
# WHOLE kde image (#285: every yellowfin:kde build errored on
# `No match for argument: kf6-config-devel`, which in turn blocked the entire
# stage-3 -hwe/-nvidia lineup). Probe first; if any build dep is missing, skip
# the source build with a warning rather than failing the image. kcm_ublue is
# a nice-to-have KDE control module, not essential to a working desktop.
missing_deps=()
for pkg in "${BUILD_DEPS[@]}"; do
	if ! dnf repoquery --available --qf '%{name}\n' "$pkg" 2>/dev/null | grep -qx "$pkg"; then
		missing_deps+=("$pkg")
	fi
done

if ((${#missing_deps[@]} > 0)); then
	printf '::warning title=kcm_ublue skipped (%s)::build deps unavailable in the active repos: %s\n' \
		"${IMAGE_NAME:-?}" "${missing_deps[*]}"
	echo "Skipping kcm_ublue source build."
elif ! dnf_retry -y install "${BUILD_DEPS[@]}"; then
	# The repoquery probe above only checks that a package NAME resolves in
	# the active repos — it can't see a broken *dependency* of that package.
	# tuna-os/tunaOS#1555: cmake existed in the Hummingbird repo index (probe
	# passed), but its own libjsoncpp.so.26/librhash.so.1 providers didn't,
	# so this install still failed and — before this branch existed — took
	# the whole image down under `set -e`. Same "nice to have, not
	# essential" call as the missing-package case above.
	printf '::warning title=kcm_ublue skipped (%s)::dnf install of build deps failed despite passing the repoquery probe — an unresolvable transitive dependency in the active repos.\n' \
		"${IMAGE_NAME:-?}"
	echo "Skipping kcm_ublue source build."
else
	BUILD_DIR=$(mktemp -d)
	trap 'rm -rf "$BUILD_DIR"' EXIT

	git clone --depth 1 --branch "${KCM_UBLUE_VERSION}" \
		https://github.com/ledif/kcm_ublue.git "$BUILD_DIR"

	cd "$BUILD_DIR"
	cmake -B build -DCMAKE_INSTALL_PREFIX=/usr
	cmake --build build
	cmake --install build
	cd - >/dev/null

	# Clean up build dependencies
	dnf -y remove "${BUILD_DEPS[@]}" || true
	dnf -y autoremove || true

	echo "kcm_ublue ${KCM_UBLUE_VERSION} installed."
fi

# ---- Bazaar: Flatpak app store + KRunner plugin --------------------------
# Bazaar is a Flatpak (io.github.kolunmi.Bazaar). The krunner-bazaar plugin
# talks to it over D-Bus at runtime (when the Flatpak is running).
#
# Built from source on every RPM base (Fedora and EL10 alike) — tunaOS#1323's
# package-sourcing policy audit (#1453) found this was still pulling from the
# ublue-os/packages COPR on Fedora, contradicting ROADMAP.md's own claim that
# Q2 goal #436 fully eliminated that COPR. It hadn't: this was the one
# remaining call site. EL10 already had to build from source here, because
# the COPR's krunner-bazaar RPM depends on a `bazaar` RPM that doesn't exist
# for EL10 — but the plugin only needs D-Bus at runtime, so that source build
# (a ~10s CMake KF6 plugin) works identically on Fedora. Unify on it and drop
# the COPR dependency entirely rather than keeping two paths for one plugin.
# See: ublue-os/aurora build_files/base/01-packages.sh (the COPR this
# replaces, for reference on what the plugin needs at runtime).
echo "Installing krunner-bazaar and setting up Bazaar Flatpak..."

KRUNNER_BAZAAR_VERSION="v1.3.0"
KRUNNER_BAZAAR_SRC="/tmp/krunner-bazaar-src"

# Build deps — most already present from KDE group install
dnf_retry -y install \
	cmake extra-cmake-modules \
	kf6-krunner-devel kf6-ki18n-devel kf6-kconfig-devel \
	qt6-qtbase-devel qt6-qtdeclarative-devel || true

curl -fsSL "https://github.com/bazaar-org/krunner-bazaar/archive/refs/tags/${KRUNNER_BAZAAR_VERSION}.tar.gz" |
	tar -xzf - -C /tmp
mv "/tmp/krunner-bazaar-${KRUNNER_BAZAAR_VERSION#v}" "${KRUNNER_BAZAAR_SRC}"

if cmake -B "${KRUNNER_BAZAAR_SRC}/_build" -S "${KRUNNER_BAZAAR_SRC}" \
	-DCMAKE_INSTALL_PREFIX=/usr \
	-DCMAKE_BUILD_TYPE=Release 2>&1; then
	cmake --build "${KRUNNER_BAZAAR_SRC}/_build" --parallel "$(nproc)"
	cmake --install "${KRUNNER_BAZAAR_SRC}/_build"
	echo "krunner-bazaar ${KRUNNER_BAZAAR_VERSION} built and installed from source."
else
	echo "Warning: krunner-bazaar build failed (missing KF6 devel deps?), skipping plugin."
fi
rm -rf "${KRUNNER_BAZAAR_SRC}"

# Flatpak preinstall — Bazaar will be installed on first boot
mkdir -p /usr/share/flatpak/preinstall.d
cat >/usr/share/flatpak/preinstall.d/bazaar.preinstall <<'EOF'
[Flatpak Preinstall io.github.kolunmi.Bazaar]
Branch=stable
IsRuntime=false
EOF

# Associate .flatpakref files with Bazaar (same as Aurora)
mkdir -p /usr/share/applications
if [ -f /usr/share/applications/mimeapps.list ]; then
	echo "application/vnd.flatpak.ref=io.github.kolunmi.Bazaar.desktop" >>/usr/share/applications/mimeapps.list
else
	cat >/usr/share/applications/mimeapps.list <<'EOF'
[Default Applications]
application/vnd.flatpak.ref=io.github.kolunmi.Bazaar.desktop
EOF
fi

# Remove the appstream krunner plugin — Bazaar replaces it (same as Aurora)
rm -f /usr/lib64/qt6/plugins/kf6/krunner/krunner_appstream.so

# ---- oversteer-udev: copy udev rules from upstream -----------------------
echo "Installing oversteer udev rules..."

OVERSTEER_UDEV_DIR="/usr/lib/udev/rules.d"
mkdir -p "$OVERSTEER_UDEV_DIR"

# Source: https://github.com/berarma/oversteer (upstream oversteer project)
OVERSTEER_RULES=(
	"99-logitech-wheel-perms.rules"
	"99-fanatec-wheel-perms.rules"
	"99-thrustmaster-wheel-perms.rules"
)

for rule in "${OVERSTEER_RULES[@]}"; do
	curl -fsSLo "${OVERSTEER_UDEV_DIR}/${rule}" \
		"https://raw.githubusercontent.com/berarma/oversteer/master/data/udev/${rule}"
	echo "  ${rule}"
done

echo "oversteer udev rules installed."

printf "::endgroup::\n"
