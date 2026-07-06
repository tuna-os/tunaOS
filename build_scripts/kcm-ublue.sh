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
else
	dnf_retry -y install "${BUILD_DEPS[@]}"

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

# ---- Bazaar: Flatpak app store (replaces Discover) -----------------------
# Bazaar is a Flatpak (io.github.kolunmi.Bazaar), not an RPM. The krunner-bazaar
# RPM plugin depends on a `bazaar` RPM that only exists in ublue-os/packages COPR
# on Fedora — it's not available for EL10. Instead:
#   1. Preinstall Bazaar Flatpak on first boot via flatpak preinstall.d
#   2. Set .flatpakref mime association to open in Bazaar
#   3. Remove the krunner_appstream plugin (Aurora does this too)
# See: ublue-os/aurora build_files/base/16-override-install.sh
echo "Setting up Bazaar Flatpak preinstall and mime associations..."

# Flatpak preinstall — Bazaar will be installed on first boot
mkdir -p /usr/share/flatpak/preinstall.d
cat > /usr/share/flatpak/preinstall.d/bazaar.preinstall <<'EOF'
[Flatpak Preinstall io.github.kolunmi.Bazaar]
Branch=stable
IsRuntime=false
EOF

# Associate .flatpakref files with Bazaar (same as Aurora)
mkdir -p /usr/share/applications
if [ -f /usr/share/applications/mimeapps.list ]; then
	echo "application/vnd.flatpak.ref=io.github.kolunmi.Bazaar.desktop" >> /usr/share/applications/mimeapps.list
else
	cat > /usr/share/applications/mimeapps.list <<'EOF'
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
