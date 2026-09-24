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

# Every variant shipped these two pointing at projectbluefin.io, inherited
# verbatim from the bluefin-lts script this one started as, while SUPPORT_URL
# and BUG_REPORT_URL were already ours. A user running `gnome-control-center
# info-overview` on any TunaOS image was sent to another project's front page.
# The contract missed it because it only asserted the two URLs that were
# already correct; verify-branding.sh now checks all four.
HOME_URL="https://github.com/tuna-os/tunaos"
DOCUMENTATION_URL="https://github.com/tuna-os/tunaos/tree/main/docs"
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
wahoo) CODE_NAME="Acanthocybium solandri" ;;
gurnard) CODE_NAME="Chelidonichthys lucerna" ;;
flounder | flounder-sid) CODE_NAME="Platichthys flesus" ;;
*)
	echo "ERROR: no scientific fish codename defined for variant: ${VARIANT_KEY}" \
		"(IMAGE_NAME_VARIANT=${IMAGE_NAME_VARIANT:-unset}, IMAGE_NAME=${IMAGE_NAME})" >&2
	exit 1
	;;
esac

chmod 644 $IMAGE_INFO

# Which os-release files to write.
#
# /usr/lib/os-release is the canonical one, but writing ONLY it is not enough:
# a base can ship a second, *real* /etc/os-release rather than the conventional
# symlink into /usr/lib. Arch is exactly that case — its `filesystem` package
# installs only usr/lib/os-release (verified against filesystem-2025.10.12),
# and the archlinux container image adds an independent /etc copy on top.
#
# Everything that asks "what OS is this" — systemd, GNOME About, GDM,
# fastfetch, and build_scripts/checks/verify-branding.sh:61 — looks at
# /etc/os-release first. So marlin's /usr/lib/os-release said "Marlin" while
# the file every reader consulted still said Arch Linux, with Arch's support
# URLs and archlinux-logo. Run 31013418173 reported all ten branding fields as
# upstream for exactly this reason, while image-info.json (a separate file,
# written by this same script) was correct — which is what made it look like
# the script had not run at all.
#
# `-ef` compares device+inode through symlinks, so the conventional
# /etc/os-release -> ../usr/lib/os-release layout adds nothing here and is
# left as a symlink. Only a genuinely separate file gets written twice.
#
# The two paths are overridable for tests only, the same way
# verify-branding.sh takes TUNAOS_OS_RELEASE; builds never set them.
OS_RELEASE_USR="${TUNAOS_OS_RELEASE_USR:-/usr/lib/os-release}"
OS_RELEASE_ETC="${TUNAOS_OS_RELEASE_ETC:-/etc/os-release}"
OS_RELEASE_FILES=("$OS_RELEASE_USR")
if [[ -e "$OS_RELEASE_ETC" ]] && ! [[ "$OS_RELEASE_ETC" -ef "$OS_RELEASE_USR" ]]; then
	OS_RELEASE_FILES+=("$OS_RELEASE_ETC")
fi

# Replace-or-append, never blind append, and never substitute-only.
#
# These used to be written two different wrong ways.
#
# `tee -a` is only correct when the base does not already define the key.
# Ubuntu DOES define SUPPORT_URL, so grouper shipped os-release containing BOTH
#
#   SUPPORT_URL="https://help.ubuntu.com/"          <- upstream, line 1
#   SUPPORT_URL="https://github.com/tuna-os/..."    <- ours, appended
#
# and which one wins depends entirely on the reader. Shell sourcing takes the
# last; every `grep ... | head -1` parser — including
# build_scripts/checks/verify-branding.sh — takes the FIRST, i.e. Ubuntu's. So
# the field was never "lost": it was set correctly and then out-voted by the
# copy already there. A duplicate key is worse than a missing one, because both
# readings are defensible and the file looks right to whoever greps it the way
# that agrees with them.
#
# A bare `sed s|^KEY=.*|...|` has the mirror-image flaw: it is only correct
# when the base ALREADY defines the key, and silently does nothing when it
# does not. No RPM base defines VERSION_CODENAME and Arch defines neither it
# nor VARIANT_ID, so the fish codename never landed on yellowfin, skipjack,
# albacore (#1007) or marlin (#1015) — the substitution matched no line and
# exited 0.
osr_set() {
	local key="$1" value="$2" file
	for file in "${OS_RELEASE_FILES[@]}"; do
		if grep -q "^${key}=" "$file"; then
			# `|` delimiter rather than `/`: values may contain slashes (URLs).
			sed -i "s|^${key}=.*|${key}=\"${value}\"|" "$file"
		else
			echo "${key}=\"${value}\"" >>"$file"
		fi
	done
}

# OS Release File (changed in order with upstream)
osr_set NAME "${IMAGE_PRETTY_NAME}"
osr_set VERSION_CODENAME "${CODE_NAME}"
osr_set VARIANT_ID "${IMAGE_NAME}"
osr_set PRETTY_NAME "${IMAGE_PRETTY_NAME}"
osr_set HOME_URL "${HOME_URL}"
osr_set BUG_REPORT_URL "${BUG_SUPPORT_URL}"
osr_set CPE_NAME "cpe:/o:jamesreilly:${IMAGE_NAME}-tunaos"

# Dynamically interpolate the specific variant name and logo path in the installer recipe.json
RECIPE_FILE="/etc/bootc-installer/recipe.json"
if [[ -f "${RECIPE_FILE}" ]]; then
	BASE_OS_NAME="Enterprise Linux"
	if [[ "$IS_FEDORA" == true ]]; then BASE_OS_NAME="Fedora"; fi
	if [[ "$IS_HUMMINGBIRD" == true ]]; then BASE_OS_NAME="Fedora Hummingbird"; fi
	if [[ "${IS_ELN:-false}" == true ]]; then BASE_OS_NAME="Fedora ELN"; fi
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
	if [[ "${IMAGE_FLAVOR}" == "pantheon" || "${IMAGE_FLAVOR}" == *"pantheon"* ]]; then DESKTOP_PRETTY_NAME="Pantheon"; fi

	# Pick the variant mark that ACTUALLY EXISTS in the installer's GResource.
	#
	# This line used to build 'images/${IMAGE_NAME}.png' unconditionally. Every
	# TunaOS mark in that bundle is an .svg — only bluefin, bluefin-lts and
	# dakota are .png — so the path never resolved. bootc-installer's
	# apply_icon() catches the failure and logs a warning, so the welcome
	# screen silently showed GTK's broken-image placeholder above a correctly
	# branded "Welcome to Skipjack". Seen on the live-ISO screenshot for
	# tuna-os/tunaOS#1056.
	#
	# The set below is upstream's, from bootc_installer/bootc-installer.gresource.xml:
	#   images/tunaos.svg  bonito.svg  skipjack.svg  albacore.svg  yellowfin.svg
	# grouper, marlin, redfin and sailfin have no mark of their own, and would
	# hit exactly the same broken placeholder — they fall back to the TunaOS
	# mark, which is branding rather than breakage.
	case "${IMAGE_NAME}" in
	tunaos | bonito | skipjack | albacore | yellowfin)
		DISTRO_LOGO_RES="resource:///org/bootcinstaller/Installer/images/${IMAGE_NAME}.svg"
		;;
	*)
		DISTRO_LOGO_RES="resource:///org/bootcinstaller/Installer/images/tunaos.svg"
		;;
	esac

	python3 -c "
import json
with open('${RECIPE_FILE}', 'r') as f:
    recipe = json.load(f)
recipe['distro_name'] = '${IMAGE_PRETTY_NAME}'
recipe['welcome_title'] = 'Welcome to ${IMAGE_PRETTY_NAME}'
recipe['distro_logo'] = '${DISTRO_LOGO_RES}'
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

# LOGO names the distro icon read by GNOME About, GDM, KDE and fastfetch.
# We ship the asset at /usr/share/pixmaps/tunaos.svg (repo system_files), so
# the verify-branding.sh asset check passes too.
osr_set LOGO "tunaos"

# Each variant wears its own Noto Emoji (the ones in .github/build-config.yml:
# marlin 🚀, yellowfin 🐠, ...), not one generic fish. system_files ships them
# all under /usr/share/tunaos/logos; install this variant's over the tunaos
# icon every consumer already points at (os-release LOGO, the GDM logo key,
# the KDE splash), so none of those paths change. Runs after system_files is
# laid down in every Containerfile, including the overlay re-copy. A variant
# with no mark keeps the 🐟 that system_files ships as tunaos.svg.
VARIANT_LOGO="/usr/share/tunaos/logos/${VARIANT_KEY}.svg"
if [[ -f "${VARIANT_LOGO}" ]]; then
	install -Dm0644 "${VARIANT_LOGO}" /usr/share/pixmaps/tunaos.svg
	install -Dm0644 "${VARIANT_LOGO}" /usr/share/icons/hicolor/scalable/apps/tunaos.svg
	for splash in /usr/share/plasma/look-and-feel/org.tunaos*.desktop/contents/splash/images/tunaos_logo.svgz; do
		[[ -f "${splash}" ]] && gzip -9nc "${VARIANT_LOGO}" >"${splash}"
	done
	echo "Variant logo: ${VARIANT_LOGO}"
else
	echo "No variant logo for ${VARIANT_KEY}; keeping the generic TunaOS mark"
fi

# ── Variant identity: TunaOS first, with a nod to the base ──────────────────
#
# build_scripts/lib/variant-identity.tsv gives each variant one accent colour
# borrowed from its base distro (Arch blue, Ubuntu orange, openSUSE green...).
# Everything below spends it: the wallpaper scene (rendered in that colour),
# os-release ANSI_COLOR (systemd's "Welcome to Marlin!" at boot), the console
# login banner and fastfetch. The desktop hooks (gnome-set-branding.sh,
# kde-set-look-and-feel.sh, cosmic-set-branding.sh) read the identity file
# written here, because on most bases they run after this script and after
# the desktop's own packages, which would overwrite anything set this early.
IDENTITY_TSV="/run/context/build_scripts/lib/variant-identity.tsv"
IDENTITY_ROW=""
if [[ -f "${IDENTITY_TSV}" ]]; then
	IDENTITY_ROW="$(awk -F'\t' -v id="${VARIANT_KEY}" '$1 == id' "${IDENTITY_TSV}")"
fi
if [[ -n "${IDENTITY_ROW}" ]]; then
	IFS=$'\t' read -r _ ACCENT GNOME_ACCENT BASE_LABEL HOMAGE <<<"${IDENTITY_ROW}"
	ACCENT_HEX="${ACCENT#\#}"
	ACCENT_R=$((16#${ACCENT_HEX:0:2}))
	ACCENT_G=$((16#${ACCENT_HEX:2:2}))
	ACCENT_B=$((16#${ACCENT_HEX:4:2}))

	osr_set ANSI_COLOR "38;2;${ACCENT_R};${ACCENT_G};${ACCENT_B}"

	install -d /usr/share/tunaos
	cat >/usr/share/tunaos/identity.env <<EOF
# Written by build_scripts/90-image-info.sh from variant-identity.tsv.
TUNAOS_VARIANT='${VARIANT_KEY}'
TUNAOS_ACCENT='${ACCENT}'
TUNAOS_ACCENT_RGB='${ACCENT_R},${ACCENT_G},${ACCENT_B}'
TUNAOS_GNOME_ACCENT='${GNOME_ACCENT}'
TUNAOS_BASE='${BASE_LABEL}'
TUNAOS_HOMAGE='${HOMAGE}'
EOF

	# The variant's scene becomes the default wallpaper every desktop points
	# at. All fourteen stay installed, so a user can pick a sibling's.
	VARIANT_WALLPAPER="/usr/share/backgrounds/tunaos/${VARIANT_KEY}.jpg"
	if [[ -f "${VARIANT_WALLPAPER}" ]]; then
		install -m0644 "${VARIANT_WALLPAPER}" /usr/share/backgrounds/tunaos/tunaos-default.jpg
	fi

	# Console login banner. Upstream's names the upstream distro ("Ubuntu
	# 26.04 LTS \n \l", "Arch Linux \r (\l)"); \S{PRETTY_NAME} is agetty's
	# own os-release lookup, so this stays right if the name ever changes.
	ESC=$'\e'
	printf '%s\n' \
		"${ESC}[1;38;2;${ACCENT_R};${ACCENT_G};${ACCENT_B}m\\S{PRETTY_NAME}${ESC}[0m - built on ${BASE_LABEL}" \
		"\\r (\\l)" \
		"" >/etc/issue

	# fastfetch: a TunaOS fish in the variant's colour instead of the base
	# distro's ASCII logo, which fastfetch otherwise picks from ID=.
	install -d /etc/xdg/fastfetch
	cat >/etc/xdg/fastfetch/config.jsonc <<EOF
// Written by build_scripts/90-image-info.sh: ${VARIANT_KEY}, in ${HOMAGE}.
{
  "\$schema": "https://github.com/fastfetch-cli/fastfetch/raw/dev/doc/json_schema.json",
  "logo": {
    "type": "file",
    "source": "/usr/share/tunaos/fastfetch-logo.txt",
    "color": { "1": "38;2;${ACCENT_R};${ACCENT_G};${ACCENT_B}" },
    "padding": { "top": 1, "right": 3 }
  },
  "display": { "color": { "keys": "38;2;${ACCENT_R};${ACCENT_G};${ACCENT_B}" } },
  "modules": [
    "title", "separator", "os", "host", "kernel", "uptime", "packages",
    "shell", "de", "wm", "terminal", "cpu", "gpu", "memory", "disk", "break", "colors"
  ]
}
EOF
	echo "Variant identity: ${VARIANT_KEY} accent=${ACCENT} (${HOMAGE})"
else
	echo "No identity row for ${VARIANT_KEY} in variant-identity.tsv; generic TunaOS look"
fi

printf "::endgroup::\n"
