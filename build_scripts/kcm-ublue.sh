#!/usr/bin/env bash
# Build and install kcm_ublue and krunner-bazaar from source/releases,
# and copy oversteer udev rules.
#
# Called during KDE image builds (kde.sh "base" or "extra").
# Uses pinned versions from image-versions.yaml (managed by Renovate).
#
# These packages were previously pulled from the ublue-os/packages COPR,
# which dropped EPEL/CentOS chroots (~2026-06-08).
# Bluefin LTS adopted the same curl-then-install approach for uupd;
# we extend it here to the KDE-specific packages.

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

printf "::group:: === KCM Ublue + Krunner Bazaar + Oversteer Udev ===\n"

# ---- Version pins --------------------------------------------------------
KCM_UBLUE_VERSION=$(grep '^\s*kcm_ublue:' /run/context/image-versions.yaml | sed 's/.*"\(.*\)".*/\1/')
KRUNNER_BAZAAR_VERSION=$(grep '^\s*krunner-bazaar:' /run/context/image-versions.yaml | sed 's/.*"\(.*\)".*/\1/')

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

# ---- krunner-bazaar: install from GitHub release RPM ---------------------
echo "Installing krunner-bazaar ${KRUNNER_BAZAAR_VERSION} from GitHub release..."

KRUNNER_RPM="krunner-bazaar-${KRUNNER_BAZAAR_VERSION#v}-1.fc43.${RPM_ARCH}.rpm"
KRUNNER_URL="https://github.com/bazaar-org/krunner-bazaar/releases/download/${KRUNNER_BAZAAR_VERSION}/${KRUNNER_RPM}"

# krunner-bazaar only publishes x86_64 RPMs; skip on other arches
if curl -fsSLI "$KRUNNER_URL" >/dev/null 2>&1; then
    curl -fsSLo "/tmp/${KRUNNER_RPM}" "$KRUNNER_URL"
    dnf_retry -y install "/tmp/${KRUNNER_RPM}" || echo "Warning: krunner-bazaar installation failed (likely missing bazaar package in EPEL), skipping."
    rm -f "/tmp/${KRUNNER_RPM}"
    echo "krunner-bazaar ${KRUNNER_BAZAAR_VERSION} installed."
else
    echo "krunner-bazaar ${KRUNNER_BAZAAR_VERSION} not available for ${RPM_ARCH} (skipping)"
fi

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
