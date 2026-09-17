#!/usr/bin/env bash
# Point the GNOME session at the TunaOS assets the image already carries.
#
# WHY THIS EXISTS
#
# marlin:gnome looked entirely unbranded and passed every check we had. Read
# straight out of the registry, the published image carries all three assets:
#
#   /usr/share/pixmaps/tunaos.svg                        4742 bytes
#   /usr/share/backgrounds/tunaos/tunaos-default.png   309864 bytes
#   /usr/share/plymouth/themes/default.plymouth        symlink to shark
#
# and nothing anywhere told GNOME to use any of them. No dconf keyfile in the
# tree mentions picture-uri, so a first login shows the stock wallpaper from
# whichever distro the variant is built on. verify-branding.sh asks whether the
# wallpaper FILE exists, which it does, so the cell stayed green.
#
# A file under /usr/share/backgrounds changes nothing on its own. This script is
# the part that was missing. See docs/BRANDING.md for the three layers and which
# desktop owns which.
#
# WHY A SCRIPT AND NOT system_files
#
# The keyfiles have to land on GNOME images only. /etc/dconf/db/local.d on a
# base with no dconf would leave an uncompiled keyfile directory, and
# verify-branding.sh fails an image whose keyfile directory has no compiled
# database. GNOME depends on dconf, so inside the GNOME install path the tool is
# always there.
#
# Both desktop install paths must call this. install-desktop.sh covers the dnf,
# zypper, pacman and portage bases; configure-desktop-runtime.sh covers Ubuntu
# and Debian. kde-set-look-and-feel.sh records what happens otherwise: the fix
# lived in one path and half the matrix shipped unbranded.
#
# No dconf LOCKS are written. These are defaults. A user who changes their
# wallpaper should keep the change.
#
# USAGE
#   gnome-set-branding.sh            # the real image paths
#   gnome-set-branding.sh <root>     # write under <root> instead (tests)

set -euo pipefail

root="${1:-}"

WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.png
LOGO=/usr/share/pixmaps/tunaos.svg

local_d="${root}/etc/dconf/db/local.d"
gdm_d="${root}/etc/dconf/db/gdm.d"

# Refuse to point the session at an asset that is not there: a dconf key naming
# a missing file renders as a black desktop, which looks like a broken image
# rather than an unbranded one. Only checked against a real root — under a test
# root the assets live on the host, not in the fixture.
if [[ -z "$root" ]]; then
	for asset in "$WALLPAPER" "$LOGO"; do
		if [[ ! -e "$asset" ]]; then
			echo "ERROR: ${asset} is missing; system_files should have placed it." >&2
			echo "       Pointing dconf at an absent file ships a black desktop." >&2
			exit 1
		fi
	done
fi

# A keyfile directory with no compiled database FAILS verify-branding.sh, which
# walks /etc/dconf/db/*.d and requires a compiled database for each. So on a
# base with no dconf at all, write nothing: an unbranded image is bad, and an
# image that newly fails its own branding contract because of this script is
# worse. GNOME depends on dconf, so this branch should never be taken — say so
# loudly if it is.
if [[ -z "$root" ]] && ! command -v dconf >/dev/null 2>&1; then
	echo "WARNING: dconf is absent on a GNOME image; skipping branding keyfiles." >&2
	echo "         The session will show the upstream wallpaper. See docs/BRANDING.md." >&2
	exit 0
fi

mkdir -p "$local_d" "$gdm_d"

# picture-uri-dark matters as much as picture-uri: GNOME 42 and later pick the
# dark variant whenever the user runs the dark style, and leaving it unset shows
# the distro default there while the light theme looks branded.
cat >"${local_d}/10-tunaos-branding" <<EOF
# Managed by build_scripts/desktop/gnome-set-branding.sh — see docs/BRANDING.md
[org/gnome/desktop/background]
picture-uri='file://${WALLPAPER}'
picture-uri-dark='file://${WALLPAPER}'
picture-options='zoom'

[org/gnome/desktop/screensaver]
picture-uri='file://${WALLPAPER}'
picture-options='zoom'
EOF

# The greeter reads its own database, not local. A logo set only in local never
# reaches the login screen, which is the first branded surface a user sees.
cat >"${gdm_d}/10-tunaos-branding" <<EOF
# Managed by build_scripts/desktop/gnome-set-branding.sh — see docs/BRANDING.md
[org/gnome/login-screen]
logo='${LOGO}'
EOF

# Compile here rather than relying on the caller. install-desktop.sh runs
# `dconf update` BEFORE the branding block, so a keyfile written in that block
# would sit uncompiled until first boot — and verify-branding.sh fails exactly
# that state.
if [[ -z "$root" ]]; then
	dconf update || true
	# Assert the compile, rather than trusting it. An uncompiled keyfile is
	# both unbranded AND a verify-branding.sh failure, and a build-time error
	# naming the database beats either.
	for db in local gdm; do
		if [[ ! -s "/etc/dconf/db/${db}" ]]; then
			echo "ERROR: wrote /etc/dconf/db/${db}.d but ${db} did not compile." >&2
			echo "       \`dconf update\` did not produce it; the session would be unbranded." >&2
			exit 1
		fi
	done
fi

echo "GNOME branding applied: wallpaper=${WALLPAPER} logo=${LOGO}"
