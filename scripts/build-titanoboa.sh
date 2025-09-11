#!/usr/bin/env bash

set -euo pipefail

# Script to build TunaOS images using the Titanoboa builder
# Usage: build-titanoboa.sh <variant> <flavor> <repo> [hook_script]
#   variant: yellowfin, albacore, skipjack, bonito
#   flavor: base, dx, gdx
#   repo: local, ghcr
#   hook_script: optional post_rootfs hook script (default: ../iso_files/configure_lts_iso_anaconda.sh)
GITHUB_REPOSITORY_OWNER="${GITHUB_REPOSITORY_OWNER:-tuna-os}"

variant="$1"
flavor="${2:-base}"
repo="${3:-local}"
hook_script="${4:-iso_files/configure_lts_iso_anaconda.sh}"
flatpaks_file="${5:-system_files/etc/ublue-os/system-flatpaks.list}"

BUILD_DIR=.build/${variant}-${flavor}
# Map variants to distros for TITANOBOA_BUILDER_DISTRO
case "$variant" in
"yellowfin" | "almalinux-kitten")
	IMAGE_DISTRO="almalinux"
	;;
"albacore" | "almalinux")
	IMAGE_DISTRO="almalinux"
	;;
"skipjack" | "centos" | "lts")
	IMAGE_DISTRO="centos"
	;;
"bonito" | "fedora" | "bluefin")
	IMAGE_DISTRO="fedora"
	;;
*)
	echo "Unknown variant: $variant" >&2
	exit 1
	;;
esac

# Construct the image URI
if [ "$flavor" != "base" ]; then
	FLAVOR_SUFFIX="-$flavor"
else
	FLAVOR_SUFFIX=""
fi

if [ "$repo" = "ghcr" ]; then
	IMAGE_NAME="ghcr.io/${GITHUB_REPOSITORY_OWNER}/${variant}${FLAVOR_SUFFIX}:latest"
elif [ "$repo" = "local" ]; then
	IMAGE_NAME="localhost/${variant}${FLAVOR_SUFFIX}:latest"
else
	echo "Unknown repo: $repo. Use 'local' or 'ghcr'" >&2
	exit 1
fi

echo -e "\n\033[1;36m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
echo -e "\033[1;33m                        Building with Titanoboa\033[0m"
echo -e "\033[1;36m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
echo -e "  \033[1;32mVariant:\033[0m       $variant"
echo -e "  \033[1;32mFlavor:\033[0m        $flavor"
echo -e "  \033[1;32mRepo:\033[0m          $repo"
echo -e "  \033[1;32mImage Distro:\033[0m  $IMAGE_DISTRO"
echo -e "  \033[1;32mImage Name:\033[0m    $IMAGE_NAME"
echo -e "  \033[1;32mHook Script:\033[0m   $hook_script"
echo -e "  \033[1;32mFlatpaks File:\033[0m $flatpaks_file"
echo -e "\033[1;36m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"

# Clean up any previous copy of Titanoboa that might have sudo permissions
if [ -d "$BUILD_DIR" ]; then
	echo "Cleaning up previous Titanoboa build directory..."
	sudo rm -rf "$BUILD_DIR"
fi

# Clone Titanoboa if not already present
if [ ! -d "$BUILD_DIR" ]; then
	echo "Cloning Titanoboa builder..."
	git clone https://github.com/ublue-os/titanoboa "$BUILD_DIR"
fi

# Copy flatpaks file to $BUILD_DIR directory for Titanoboa to use
echo "Copying flatpaks file to $BUILD_DIR directory..."
cp "$flatpaks_file" "$BUILD_DIR/flatpaks.list"

echo "Copying hook script to $BUILD_DIR directory..."
cp "$hook_script" "$BUILD_DIR/hook.sh"

# Change to the $BUILD_DIR directory
cd "$BUILD_DIR"

# Run the Titanoboa build command
echo "Running Titanoboa build..."
sudo TITANOBOA_BUILDER_DISTRO="$IMAGE_DISTRO" \
	HOOK_post_rootfs="hook.sh" \
	just build "$IMAGE_NAME" 1 flatpaks.list

echo "Titanoboa build completed successfully!"
