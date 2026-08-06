#!/usr/bin/env bash

set -xeuo pipefail
printf "::group:: === 90 Image Info ===\n"

source /run/context/build_scripts/lib.sh

# Fold a friendly alias tag onto the canonical variant id it belongs to.
#
# Mirrors the `aliases:` lists in .github/build-config.yml. An alias is only a
# second tag for the same digest, so it must never become the image's identity
# (VARIANT_ID/hostname) and it is not a valid key for the codename table below.
canonical_variant() {
	case "$1" in
	almalinux-kitten) echo yellowfin ;;
	almalinux) echo albacore ;;
	centos) echo skipjack ;;
	fedora) echo bonito ;;
	opensuse | tumbleweed) echo sailfin ;;
	gentoo) echo guppy ;;
	elementary) echo gurnard ;;
	ubuntu) echo grouper ;;
	arch | archlinux) echo marlin ;;
	debian) echo flounder ;;
	*) echo "$1" ;;
	esac
}

# lib.sh derives IMAGE_NAME from the detected base whenever the Containerfile
# does not pin it, and that derivation hands back the distro alias (sailfin
# builds arrive here as "opensuse" and guppy as "gentoo"), which would brand the
# image with the alias and abort the codename lookup below. Canonicalize first.
IMAGE_NAME="$(canonical_variant "${IMAGE_NAME:-${IMAGE_NAME_VARIANT:-}}")"

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

# TunaOS variants are named for fish. Keep VERSION_CODENAME tied to that
# identity instead of inheriting the unrelated legacy dinosaur codename.
# Generic common names use one stable representative species.
#
# Keyed on the canonical variant id, not on IMAGE_NAME: IMAGE_NAME carries the
# *publish* name (`bonito` for bonito-rawhide, `flounder` for flounder-sid) and,
# on bases where the Containerfile does not pin it, whatever lib.sh derived from
# the base image. IMAGE_NAME_VARIANT is the variant id build-image-inner.sh
# passes verbatim, so prefer it and fall back to the canonicalized IMAGE_NAME.
VARIANT_KEY="$(canonical_variant "${IMAGE_NAME_VARIANT:-${IMAGE_NAME}}")"
case "${VARIANT_KEY}" in
yellowfin) CODE_NAME="Thunnus albacares" ;;
albacore) CODE_NAME="Thunnus alalunga" ;;
skipjack) CODE_NAME="Katsuwonus pelamis" ;;
bonito | bonito-rawhide) CODE_NAME="Sarda sarda" ;;
sailfin) CODE_NAME="Istiophorus platypterus" ;;
guppy) CODE_NAME="Poecilia reticulata" ;;
grouper) CODE_NAME="Epinephelus marginatus" ;;
marlin) CODE_NAME="Makaira nigricans" ;;
hummingbird) CODE_NAME="Trochilidae" ;;
gurnard) CODE_NAME="Chelidonichthys lucerna" ;;
flounder | flounder-sid) CODE_NAME="Platichthys flesus" ;;
*)
	echo "ERROR: no scientific fish codename defined for variant: ${VARIANT_KEY}" \
		"(IMAGE_NAME_VARIANT=${IMAGE_NAME_VARIANT:-unset}, IMAGE_NAME=${IMAGE_NAME})" >&2
	exit 1
	;;
esac

chmod 644 $IMAGE_INFO

# Every os-release path a reader can resolve, not just the canonical one.
#
# /etc/os-release is *conventionally* a symlink to ../usr/lib/os-release, and on
# the dnf, apt, zypper and portage bases it is, so writing the canonical file was
# enough. The official archlinux/archlinux container is the exception: the
# `filesystem` package ships only /usr/lib/os-release plus that symlink, but the
# image's second layer overwrites /etc/os-release with a 411-byte *regular file*
# holding stock Arch identity. Editing /usr/lib/os-release therefore left marlin
# with two different identities on disk, and every consumer that reads
# /etc/os-release (`. /etc/os-release`, and verify-branding.sh, which prefers it)
# saw the upstream one:
#
#   PRETTY_NAME="Arch Linux"   SUPPORT_URL="https://bbs.archlinux.org/"
#   LOGO=archlinux-logo        BUG_REPORT_URL="https://gitlab.archlinux.org/..."
#
# i.e. all ten TUNAOS_BRANDING_FAIL findings on the marlin:gnome LUKS build,
# reported against an image whose /usr/lib/os-release was branded correctly.
#
# Rather than replace the file with a symlink (which would drop the keys the
# container adds only there, e.g. Arch's dated VERSION_ID), brand every distinct
# file so both readings agree.
OS_RELEASE_FILES=(/usr/lib/os-release)
if [[ -e /etc/os-release ]] &&
	[[ "$(readlink -f /etc/os-release)" != "$(readlink -f /usr/lib/os-release)" ]]; then
	OS_RELEASE_FILES+=(/etc/os-release)
fi

# OS Release File (changed in order with upstream)
OSR_SED_PROGRAM="$(
	cat <<EOF
s/^NAME=.*/NAME=\"${IMAGE_PRETTY_NAME}\"/
s|^VERSION_CODENAME=.*|VERSION_CODENAME=\"${CODE_NAME}\"|
s/^VARIANT_ID=.*/VARIANT_ID=${IMAGE_NAME}/
s|^PRETTY_NAME=.*|PRETTY_NAME=\"${IMAGE_PRETTY_NAME}\"|
s|^HOME_URL=.*|HOME_URL=\"${HOME_URL}\"|
s|^BUG_REPORT_URL=.*|BUG_REPORT_URL=\"${BUG_SUPPORT_URL}\"|
s|^CPE_NAME=.*|CPE_NAME=\"cpe:/o:jamesreilly:${IMAGE_NAME}-tunaos\"|
EOF
)"
for osr_file in "${OS_RELEASE_FILES[@]}"; do
	printf '%s\n' "${OSR_SED_PROGRAM}" | sed -i -f - "${osr_file}"
done

# Dynamically interpolate the specific variant name and logo path in the installer recipe.json
RECIPE_FILE="/etc/bootc-installer/recipe.json"
if [[ -f "${RECIPE_FILE}" ]]; then
	BASE_OS_NAME="Enterprise Linux"
	if [[ "$IS_FEDORA" == true ]]; then BASE_OS_NAME="Fedora"; fi
	if [[ "$IS_HUMMINGBIRD" == true ]]; then BASE_OS_NAME="Fedora Hummingbird"; fi
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
for osr_file in "${OS_RELEASE_FILES[@]}"; do
	if ! grep -q "^VARIANT_ID=" "${osr_file}"; then
		echo "VARIANT_ID=${IMAGE_NAME}" >>"${osr_file}"
	fi
done

# Replace-or-append, never blind append.
#
# These four used to be written with `tee -a`, which is only correct when the
# base does not already define the key. Ubuntu DOES define SUPPORT_URL, so
# grouper shipped os-release containing BOTH
#
#   SUPPORT_URL="https://help.ubuntu.com/"          <- upstream, line 1
#   SUPPORT_URL="https://github.com/tuna-os/..."    <- ours, appended
#
# and which one wins depends entirely on the reader. Shell sourcing takes the
# last; every `grep ... | head -1` parser — including
# build_scripts/checks/verify-branding.sh:74 — takes the FIRST, i.e. Ubuntu's.
# So the field was never "lost": it was set correctly and then out-voted by the
# copy already there. A duplicate key is worse than a missing one, because both
# readings are defensible and the file looks right to whoever greps it the way
# that agrees with them.
osr_set() {
	local key="$1" value="$2" file
	for file in "${OS_RELEASE_FILES[@]}"; do
		if grep -q "^${key}=" "${file}"; then
			# `|` delimiter rather than `/`: values may contain slashes (URLs).
			sed -i "s|^${key}=.*|${key}=\"${value}\"|" "${file}"
		else
			echo "${key}=\"${value}\"" >>"${file}"
		fi
	done
}

osr_set DOCUMENTATION_URL "${DOCUMENTATION_URL}"
osr_set SUPPORT_URL "${SUPPORT_URL}"
osr_set DEFAULT_HOSTNAME "${IMAGE_NAME}"
osr_set BUILD_ID "${SHA_HEAD_SHORT:-testing}"

# Set by bluefin and read by desktop UIs, bootc and fastfetch to name the
# system; we set none of them, so those surfaces fell back to the upstream
# identity. IMAGE_VERSION carries the flavor as well as the build, because a
# grouper:kde and a grouper:gnome from the same commit are not interchangeable
# and "which image is this" is the question the field exists to answer.
osr_set VARIANT "${IMAGE_PRETTY_NAME} ${IMAGE_FLAVOR}"
osr_set IMAGE_ID "${IMAGE_NAME}"
osr_set IMAGE_VERSION "${IMAGE_FLAVOR}-${SHA_HEAD_SHORT:-testing}"

# NAME, PRETTY_NAME, VERSION_CODENAME, BUG_REPORT_URL — these are handled by
# the sed block at the top for distros that already ship the keys. For distros
# that omit them (Arch, Gentoo, openSUSE have no VERSION_CODENAME etc.), the
# sed is a no-op and osr_set appends them.
osr_set NAME "${IMAGE_PRETTY_NAME}"
osr_set PRETTY_NAME "${IMAGE_PRETTY_NAME}"
osr_set VERSION_CODENAME "${CODE_NAME}"
osr_set BUG_REPORT_URL "${BUG_SUPPORT_URL}"
osr_set HOME_URL "${HOME_URL}"

# LOGO names the distro icon read by GNOME About, GDM, KDE and fastfetch.
# We ship the asset at /usr/share/pixmaps/tunaos.svg (repo system_files), so
# the verify-branding.sh asset check passes too.
osr_set LOGO "tunaos"

printf "::endgroup::\n"
