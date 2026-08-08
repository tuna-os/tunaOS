#!/usr/bin/env bash

set -euo pipefail

source /run/context/build_scripts/lib.sh

# Set ENABLE_NVIDIA for nvidia-specific scripts
export ENABLE_NVIDIA="${ENABLE_NVIDIA:-1}"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export DESKTOP_FLAVOR

printf "::group:: === nvidia ===\n"

if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	copy_systemfiles_for kde-nvidia
	run_buildscripts_for kde-nvidia
elif [[ "${DESKTOP_FLAVOR}" == "niri" ]]; then
	copy_systemfiles_for niri-nvidia
	run_buildscripts_for niri-nvidia
fi

# Generic VS Code setup hooks (system_files_overrides/nvidia) apply to every
# family, so this stays unconditional.
copy_systemfiles_for nvidia

# Package-manager dispatch (tunaOS#624): the akmods/RPM path below is the
# original one and stays exactly as it was — marlin (Arch) and
# flounder/flounder-sid (Debian) have no akmods bundle to consume and use
# pacman/dkms and apt/dkms respectively instead. IS_ARCH/IS_DEBIAN/PKG_MGR
# come from lib.sh's cached OS detection, already sourced above.
#
# Each branch runs its OWN install override directory (run_buildscripts_for
# nvidia-arch / nvidia-debian / nvidia, never all three — the RPM overrides
# call rpm/dnf directly and would fail outright on a pacman or apt base) and
# its own fatal contract script. Every branch's contract call is a bare
# statement under `set -e`, same as before this dispatch existed: an nvidia
# overlay that did not actually install the driver stack fails the build
# here rather than publishing (that silent-skip is the exact failure mode
# verify-nvidia.sh's header documents). Each contract script is also
# installed into the image so desktop-contract-sweep can re-run it against
# published tags.
if [[ "${IS_ARCH:-false}" == "true" ]]; then
	run_buildscripts_for nvidia-arch
	/run/context/build_scripts/checks/verify-nvidia-arch.sh
	install -Dm0755 /run/context/build_scripts/checks/verify-nvidia-arch.sh \
		/usr/libexec/tunaos/verify-nvidia
elif [[ "${IS_DEBIAN:-false}" == "true" ]]; then
	run_buildscripts_for nvidia-debian
	/run/context/build_scripts/checks/verify-nvidia-debian.sh
	install -Dm0755 /run/context/build_scripts/checks/verify-nvidia-debian.sh \
		/usr/libexec/tunaos/verify-nvidia
else
	run_buildscripts_for nvidia

	# Independent audit of what the overlay just did. run_buildscripts_for
	# returns 0 when its overrides directory is missing — exactly how
	# driverless "*-nvidia" images shipped for months — so the contract below
	# is a bare call under `set -e`: an nvidia overlay that did not actually
	# install the driver stack fails the build here rather than publishing.
	# Installed into the image too, so desktop-contract-sweep can re-run it
	# against published tags.
	/run/context/build_scripts/checks/verify-nvidia.sh
	install -Dm0755 /run/context/build_scripts/checks/verify-nvidia.sh \
		/usr/libexec/tunaos/verify-nvidia
fi

if command -v jq >/dev/null 2>&1; then
	jq . /usr/share/ublue-os/image-info.json || true
else
	cat /usr/share/ublue-os/image-info.json || true
fi
detected_os
printf "::endgroup::\n"
