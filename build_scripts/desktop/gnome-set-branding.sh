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
#   /usr/share/plymouth/themes/default.plymouth        symlink to tunaos.plymouth
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
# Tuna shares GDM, not GNOME's wallpaper consumer. Restrict its integration to
# the greeter database/profile; do not alter its user-session defaults.
desktop="${TUNAOS_BRANDING_DESKTOP:-gnome}"

WALLPAPER=/usr/share/backgrounds/tunaos/tunaos-default.jpg
# The login screen shows the variant's lettermark (its emoji and name, e.g.
# "🚀 Marlin"), which 90-image-info.sh installs from
# /usr/share/tunaos/lettermarks/<variant>.svg; the variant is the brand.
# verify-branding-gnome.sh accepts only those bytes, so there is no fallback to
# the square mark: the asset check below stops the build when it is missing.
LOGO=/usr/share/pixmaps/tunaos-lettermark.svg

local_d="${root}/etc/dconf/db/local.d"
gdm_d="${root}/etc/dconf/db/gdm.d"
profile="${root}/etc/dconf/profile/user"

# The variant's accent (build_scripts/lib/variant-identity.tsv), written by
# 90-image-info.sh. Absent on an image built before it existed: then no accent.
GNOME_ACCENT=""
identity="${root}/usr/share/tunaos/identity.env"
if [[ -f "$identity" ]]; then
	GNOME_ACCENT="$(sed -n 's/^TUNAOS_GNOME_ACCENT=//p' "$identity" | tr -d "'\"")"
fi

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

mkdir -p "$gdm_d" "$(dirname "$profile")"

if [[ "$desktop" != tuna ]]; then
	mkdir -p "$local_d"
	# A keyfile in local.d is only read if the user profile names system-db:local.
	# Fedora and EL ship that profile; Ubuntu, Debian, Arch and Gentoo ship none,
	# and with no profile dconf reads the user database alone. So the wallpaper
	# below compiled fine and was never applied there: the session showed the
	# distro default. Write the profile if it is missing, and add the line if a
	# base ships one without it.
	if [[ ! -f "$profile" ]]; then
		mkdir -p "$(dirname "$profile")"
		printf 'user-db:user\nsystem-db:local\n' >"$profile"
	elif ! grep -qx 'system-db:local' "$profile"; then
		echo 'system-db:local' >>"$profile"
	fi
fi

# GDM uses DCONF_PROFILE=gdm, not the user's profile. Preserve packaged defaults
# when adding our system database; a compiled gdm blob without this consumer
# routing cannot supply the login-screen logo.
gdm_profile="${root}/etc/dconf/profile/gdm"
if [[ ! -f "$gdm_profile" ]]; then
	if [[ -f "${root}/usr/share/dconf/profile/gdm" ]]; then
		cp "${root}/usr/share/dconf/profile/gdm" "$gdm_profile"
	else
		printf 'user-db:user\n' >"$gdm_profile"
		if [[ -f "${root}/usr/share/gdm/greeter-dconf-defaults" ]]; then
			printf 'file-db:/usr/share/gdm/greeter-dconf-defaults\n' >>"$gdm_profile"
		fi
	fi
fi
if ! grep -qx 'system-db:gdm' "$gdm_profile"; then
	# Put ours before packaged read-only defaults, after the user database.
	awk '/^file-db:/ && !added {print "system-db:gdm"; added=1}
		{print} END {if (!added) print "system-db:gdm"}' "$gdm_profile" >"${gdm_profile}.tmp"
	mv "${gdm_profile}.tmp" "$gdm_profile"
fi

if [[ "$desktop" != tuna ]]; then
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

	# The accent borrows the base distro's colour (orange on grouper, green on
	# sailfin). GNOME before 47 has no accent-color key; dconf ignores a key no
	# schema defines, so writing it there is harmless.
	if [[ -n "$GNOME_ACCENT" ]]; then
		cat >>"${local_d}/10-tunaos-branding" <<EOF

[org/gnome/desktop/interface]
accent-color='${GNOME_ACCENT}'
EOF
	fi
fi

# The greeter reads its own database, not local. A logo set only in local never
# reaches the login screen, which is the first branded surface a user sees.
cat >"${gdm_d}/10-tunaos-branding" <<EOF
# Managed by build_scripts/desktop/gnome-set-branding.sh — see docs/BRANDING.md
[org/gnome/login-screen]
logo='${LOGO}'
EOF

# The greeter is gnome-shell in GDM mode and draws with the gdm database's
# accent. Tuna keeps its own greeter accent path (tuna-gdm-theme.sh).
if [[ "$desktop" != tuna && -n "$GNOME_ACCENT" ]]; then
	cat >>"${gdm_d}/10-tunaos-branding" <<EOF

[org/gnome/desktop/interface]
accent-color='${GNOME_ACCENT}'
EOF
fi

# GNOME Initial Setup does NOT read the gdm profile. GDM starts it with
# DCONF_PROFILE=gnome-initial-setup (gdm daemon/gdm-launch-environment.c,
# INITIAL_SETUP_DCONF_PROFILE), and the packaged profile is only
# `user-db:user` plus GIS's own file-db, so no system database reaches it.
# Measured on bonito:gnome (main 69f7e8a): that profile reads no accent-color,
# the schema default (slate) wins, and the Next pill is slate, not blue.
# Ubuntu's libadwaita maps slate to Yaru "sage", srgb(101,123,105): the olive
# pill on grouper (tunaOS#4408). An /etc profile overrides the packaged one,
# so copy it and add a database that holds only the accent. Tuna too: this
# is the setup session, not the user session Tuna keeps stock.
gis_profile="${root}/etc/dconf/profile/gnome-initial-setup"
gis_written=0
if [[ -n "$GNOME_ACCENT" ]] &&
	[[ -f "$gis_profile" || -f "${root}/usr/share/dconf/profile/gnome-initial-setup" ]]; then
	[[ -f "$gis_profile" ]] || cp "${root}/usr/share/dconf/profile/gnome-initial-setup" "$gis_profile"
	if ! grep -qx 'system-db:gnome-initial-setup' "$gis_profile"; then
		awk '/^file-db:/ && !added {print "system-db:gnome-initial-setup"; added=1}
			{print} END {if (!added) print "system-db:gnome-initial-setup"}' "$gis_profile" >"${gis_profile}.tmp"
		mv "${gis_profile}.tmp" "$gis_profile"
	fi
	mkdir -p "${root}/etc/dconf/db/gnome-initial-setup.d"
	cat >"${root}/etc/dconf/db/gnome-initial-setup.d/10-tunaos-branding" <<EOF
# Managed by build_scripts/desktop/gnome-set-branding.sh — see docs/BRANDING.md
[org/gnome/desktop/interface]
accent-color='${GNOME_ACCENT}'
EOF
	gis_written=1
fi

# Ubuntu patches Initial Setup with pages that sell or name Ubuntu: Ubuntu Pro,
# "Help Improve Ubuntu" (ubuntu_insights), a welcome page with the Ubuntu
# mascot and ubuntu.com release notes, a Yaru appearance picker and an App
# Center launcher (gnome-initial-setup 50.0-0ubuntu7.2, debian/patches/ubuntu).
# The page ids are the PAGE() names in its page tables. Its build carries
# those names as strings, so the binary itself says whether they exist.
# GIS loads /etc/gnome-initial-setup/vendor.conf INSTEAD of the /usr/share
# one (gis-driver.c), so start from the packaged file and add to [pages] skip.
# The welcome id only takes effect in Ubuntu mode: elsewhere GIS shows welcome
# only when the language page is skipped.
UBUNTU_GIS_PAGES="welcome;ubuntu_pro;ubuntu_insights;appearance;apps"
for gis_bin in "${root}/usr/libexec/gnome-initial-setup" "${root}/usr/lib/gnome-initial-setup"; do
	if [[ ! -f "$gis_bin" ]] || ! grep -aqw ubuntu_pro "$gis_bin"; then
		continue
	fi
	vendor="${root}/etc/gnome-initial-setup/vendor.conf"
	mkdir -p "$(dirname "$vendor")"
	if [[ ! -f "$vendor" && -f "${root}/usr/share/gnome-initial-setup/vendor.conf" ]]; then
		cp "${root}/usr/share/gnome-initial-setup/vendor.conf" "$vendor"
	fi
	touch "$vendor"
	awk -v add="$UBUNTU_GIS_PAGES" '
		function merged(have,   n, a, out, i, seen) {
			n = split(have ";" add, a, ";")
			for (i = 1; i <= n; i++) {
				gsub(/^[ \t]+|[ \t]+$/, "", a[i])
				if (a[i] == "" || (a[i] in seen)) continue
				seen[a[i]] = 1
				out = out (out == "" ? "" : ";") a[i]
			}
			return out
		}
		/^[ \t]*\[/ {
			if (in_pages && !done) { print "skip=" merged(""); done = 1 }
			in_pages = ($0 ~ /^[ \t]*\[pages\][ \t]*$/)
			if (in_pages) pages = 1
			print; next
		}
		in_pages && /^[ \t]*skip[ \t]*=/ {
			sub(/^[ \t]*skip[ \t]*=/, "")
			print "skip=" merged($0); done = 1; next
		}
		{ print }
		END {
			if (in_pages && !done) print "skip=" merged("")
			else if (!pages) { print "[pages]"; print "skip=" merged("") }
		}' "$vendor" >"${vendor}.tmp"
	mv "${vendor}.tmp" "$vendor"
	echo "Initial Setup: skipping Ubuntu pages ${UBUNTU_GIS_PAGES} via ${vendor#"$root"}"
	break
done

# Compile here rather than relying on the caller. install-desktop.sh runs
# `dconf update` BEFORE the branding block, so a keyfile written in that block
# would sit uncompiled until first boot — and verify-branding.sh fails exactly
# that state.
if [[ -z "$root" ]]; then
	dconf update || true
	# Assert the compile, rather than trusting it. An uncompiled keyfile is
	# both unbranded AND a verify-branding.sh failure, and a build-time error
	# naming the database beats either.
	for db in local gdm gnome-initial-setup; do
		[[ "$desktop" != tuna || "$db" != local ]] || continue
		[[ "$db" != gnome-initial-setup || "$gis_written" -eq 1 ]] || continue
		if [[ ! -s "/etc/dconf/db/${db}" ]]; then
			echo "ERROR: wrote /etc/dconf/db/${db}.d but ${db} did not compile." >&2
			echo "       \`dconf update\` did not produce it; the session would be unbranded." >&2
			exit 1
		fi
	done
fi

if [[ "$desktop" == tuna ]]; then
	echo "GDM branding applied: logo=${LOGO} wallpaper=not-run user_defaults=not-modified"
else
	echo "GNOME branding applied: wallpaper=${WALLPAPER} logo=${LOGO} accent=${GNOME_ACCENT:-none}"
fi
