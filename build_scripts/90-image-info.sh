#!/usr/bin/env bash

set -xeuo pipefail
printf "::group:: === 90 Image Info ===\n"

source /run/context/build_scripts/lib.sh

IMAGE_REF="ostree-image-signed:docker://${IMAGE_REGISTRY:-ghcr.io}/${IMAGE_VENDOR}/${IMAGE_NAME}"
IMAGE_INFO="/usr/share/ublue-os/image-info.json"
IMAGE_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
IMAGE_PRETTY_NAME="${IMAGE_NAME^}"

# /usr/share/ublue-os ships with UB/Fedora base images but not Ubuntu.
mkdir -p "$(dirname "$IMAGE_INFO")"

cat >$IMAGE_INFO <<EOF
  {
    "image-name": "${IMAGE_NAME}",
    "image-ref": "${IMAGE_REF}",
    "image-flavor": "${IMAGE_FLAVOR}",
    "image-vendor": "${IMAGE_VENDOR}",
    "image-tag": "latest",
    "major-version": "${MAJOR_VERSION_NUMBER}",
    "sha": "${SHA_HEAD_SHORT:-testing}",
    "base-image": "${BASE_IMAGE}"
  }
EOF

HOME_URL="https://projectbluefin.io"
DOCUMENTATION_URL="https://docs.projectbluefin.io"
SUPPORT_URL="https://github.com/tuna-os/tunaos/issues/"
BUG_SUPPORT_URL="https://github.com/tuna-os/tunaos/issues/"
CODE_NAME="Achillobator"

chmod 644 $IMAGE_INFO

# OS Release File (changed in order with upstream)
sed -i -f - /usr/lib/os-release <<EOF
s/^NAME=.*/NAME=\"${IMAGE_PRETTY_NAME}\"/
s|^VERSION_CODENAME=.*|VERSION_CODENAME=\"${CODE_NAME}\"|
s/^VARIANT_ID=.*/VARIANT_ID=${IMAGE_NAME}/
s|^PRETTY_NAME=.*|PRETTY_NAME=\"${IMAGE_PRETTY_NAME}\"|
s|^HOME_URL=.*|HOME_URL=\"${HOME_URL}\"|
s|^BUG_REPORT_URL=.*|BUG_REPORT_URL=\"${BUG_SUPPORT_URL}\"|
s|^CPE_NAME=.*|CPE_NAME=\"cpe:/o:jamesreilly:${IMAGE_NAME}-tunaos\"|
EOF

# Dynamically interpolate the specific variant name and logo path in the installer recipe.json
RECIPE_FILE="/etc/bootc-installer/recipe.json"
if [[ -f "${RECIPE_FILE}" ]]; then
	BASE_OS_NAME="Enterprise Linux"
	if [[ "$IS_FEDORA" == true ]]; then BASE_OS_NAME="Fedora"; fi
	if [[ "$IS_ALMALINUX" == true ]]; then BASE_OS_NAME="AlmaLinux"; fi
	if [[ "$IS_ALMALINUXKITTEN" == true ]]; then BASE_OS_NAME="AlmaLinux Kitten"; fi
	if [[ "$IS_CENTOS" == true ]]; then BASE_OS_NAME="CentOS Stream"; fi
	if [[ "$IS_UBUNTU" == true ]]; then BASE_OS_NAME="Ubuntu"; fi
	if [[ "$IS_DEBIAN" == true ]]; then BASE_OS_NAME="Debian"; fi
	if [[ "$IS_ARCH" == true ]]; then BASE_OS_NAME="Arch Linux"; fi
	if [[ "$IS_OPENSUSE" == true ]]; then BASE_OS_NAME="openSUSE Tumbleweed"; fi
	if [[ "$IS_GENTOO" == true ]]; then BASE_OS_NAME="Gentoo Linux"; fi

	DESKTOP_PRETTY_NAME="GNOME"
	if [[ "${IMAGE_FLAVOR}" == "kde" || "${IMAGE_FLAVOR}" == *"kde"* ]]; then DESKTOP_PRETTY_NAME="KDE Plasma"; fi
	if [[ "${IMAGE_FLAVOR}" == "cosmic" || "${IMAGE_FLAVOR}" == *"cosmic"* ]]; then DESKTOP_PRETTY_NAME="COSMIC"; fi
	if [[ "${IMAGE_FLAVOR}" == "niri" || "${IMAGE_FLAVOR}" == *"niri"* ]]; then DESKTOP_PRETTY_NAME="Niri"; fi
	if [[ "${IMAGE_FLAVOR}" == "xfce" || "${IMAGE_FLAVOR}" == *"xfce"* ]]; then DESKTOP_PRETTY_NAME="XFCE"; fi

	python3 -c "
import json
with open('${RECIPE_FILE}', 'r') as f:
    recipe = json.load(f)
recipe['distro_name'] = '${IMAGE_PRETTY_NAME}'
recipe['welcome_title'] = 'Welcome to ${IMAGE_PRETTY_NAME}'
recipe['distro_logo'] = 'resource:///org/bootcinstaller/Installer/images/${IMAGE_NAME}.png'
recipe['tour']['welcome']['title'] = 'Welcome to ${IMAGE_PRETTY_NAME}'
recipe['tour']['welcome']['description'] = '${IMAGE_PRETTY_NAME} is an immutable, container-native Linux operating system built for enterprise workstations and developers.'

# Insert custom distro and desktop slides in order
tour = recipe.get('tour', {})
new_tour = {}
if 'welcome' in tour:
    new_tour['welcome'] = tour['welcome']
if 'features' in tour:
    new_tour['features'] = tour['features']

new_tour['distro'] = {
    'image': '/run/host/usr/share/bootc-installer/images/tunaos-install.png',
    'title': 'Built on ${BASE_OS_NAME}',
    'description': '${IMAGE_PRETTY_NAME} leverages the solid foundation of stable ${BASE_OS_NAME} packages to ensure maximum compatibility and package availability.'
}

new_tour['desktop'] = {
    'image': '/run/host/usr/share/bootc-installer/images/tunaos-install.png',
    'title': '${DESKTOP_PRETTY_NAME} Desktop',
    'description': 'Enjoy a custom-integrated, modern ${DESKTOP_PRETTY_NAME} workspace configured for performance, accessibility, and style.'
}

if 'community' in tour:
    new_tour['community'] = tour['community']
if 'completed' in tour:
    new_tour['completed'] = tour['completed']

recipe['tour'] = new_tour

with open('${RECIPE_FILE}', 'w') as f:
    json.dump(recipe, f, indent=2)
" || true
fi

# Ensure VARIANT_ID is set — the sed substitution above only replaces an
# existing line; AlmaLinux base images omit it entirely.
if ! grep -q "^VARIANT_ID=" /usr/lib/os-release; then
	echo "VARIANT_ID=${IMAGE_NAME}" >>/usr/lib/os-release
fi

tee -a /usr/lib/os-release <<EOF
DOCUMENTATION_URL="${DOCUMENTATION_URL}"
SUPPORT_URL="${SUPPORT_URL}"
DEFAULT_HOSTNAME="${IMAGE_NAME}"
BUILD_ID="${SHA_HEAD_SHORT:-testing}"
EOF

printf "::endgroup::\n"
