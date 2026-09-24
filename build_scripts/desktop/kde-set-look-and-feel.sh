#!/usr/bin/env bash
# Re-assert the TunaOS Plasma look-and-feel AFTER the desktop packages land.
#
# system_files ships kdeglobals with LookAndFeelPackage=org.tunaos.desktop, but
# it is copied in during the base stage, and Fedora's kde-settings RPM owns the
# same path — so installing Plasma overwrote our file and bonito:kde shipped
# LookAndFeelPackage=org.fedoraproject.fedora.desktop (#1008). Setting it after
# the install is the only ordering that survives.
#
# This lives in its own script because there are TWO desktop install paths and
# the fix is only correct if both run it. install-desktop.sh handles the dnf,
# zypper, pacman and portage bases (bonito among them);
# configure-desktop-runtime.sh handles Ubuntu/Debian. Putting the logic in one
# of them left the other unbranded, which is exactly how the bonito:kde LUKS
# E2E kept failing on this branch with the fix nominally applied.
#
# Both config locations are written, deliberately. On Fedora/EL, kde-settings
# puts its profile dir AHEAD of /etc/xdg in XDG_CONFIG_DIRS, so writing only
# /etc/xdg would satisfy verify-branding-kde.sh (which greps /etc/xdg first)
# while Plasma still loaded Fedora's theme — passing the check without fixing
# the image, which is worse than failing it.
#
# USAGE
#   kde-set-look-and-feel.sh              # the real image paths
#   kde-set-look-and-feel.sh <file>...    # explicit files (tests)

set -euo pipefail

# Overridable for tests only; builds never set it.
LNF_WANT="${TUNAOS_KDE_LOOK_AND_FEEL:-org.tunaos.desktop}"

kde_set_lnf() {
	local file="$1" want="${LNF_WANT}"
	mkdir -p "$(dirname "$file")"
	if [[ ! -f "$file" ]]; then
		printf '[KDE]\nLookAndFeelPackage=%s\n' "$want" >"$file"
		return
	fi
	# Replace the key in [KDE] if present, else add it to that section, else
	# append the section — without disturbing anything else in the file (these
	# carry fonts, colour scheme and widget style too).
	awk -v want="$want" '
		/^\[/ { if (insec && !set) { print "LookAndFeelPackage=" want; set=1 } insec = ($0 == "[KDE]") }
		/^[ \t]*LookAndFeelPackage[ \t]*=/ { if (insec) { print "LookAndFeelPackage=" want; set=1; next } }
		{ print }
		END { if (!set) { if (!insec) print "[KDE]"; print "LookAndFeelPackage=" want } }
	' "$file" >"${file}.tunaos.tmp" && mv "${file}.tunaos.tmp" "$file"
}

if [[ $# -gt 0 ]]; then
	files=("$@")
else
	files=(/etc/xdg/kdeglobals)
	if [[ -d /usr/share/kde-settings/kde-profile/default/xdg ]]; then
		files+=(/usr/share/kde-settings/kde-profile/default/xdg/kdeglobals)
	fi
fi

for _f in "${files[@]}"; do
	kde_set_lnf "$_f"
done

# The variant's accent (build_scripts/lib/variant-identity.tsv): Breeze tints
# selections, focus rings and the panel highlight with AccentColor, so each
# variant carries its base distro's colour. Same section-aware rewrite as the
# look-and-feel key; skipped on an image with no identity file.
identity="${TUNAOS_IDENTITY:-/usr/share/tunaos/identity.env}"
accent_rgb=""
if [[ -f "$identity" ]]; then
	accent_rgb="$(sed -n 's/^TUNAOS_ACCENT_RGB=//p' "$identity" | tr -d "'\"")"
fi
if [[ -n "$accent_rgb" ]]; then
	for _f in "${files[@]}"; do
		awk -v want="$accent_rgb" '
			/^\[/ { if (insec && !set) { print "AccentColor=" want; set=1 } insec = ($0 == "[General]") }
			/^[ \t]*AccentColor[ \t]*=/ { if (insec) { print "AccentColor=" want; set=1; next } }
			{ print }
			END { if (!set) { if (!insec) print "[General]"; print "AccentColor=" want } }
		' "$_f" >"${_f}.tunaos.tmp" && mv "${_f}.tunaos.tmp" "$_f"
	done
fi

# The About page (Info Center) is one of the two places TunaOS is named at
# all; the variant is the brand everywhere else. Plasma shows Variant= under
# the OS name, so it reads "Marlin / part of TunaOS", with the variant's mark
# and our website. Written after the install: Fedora's kde-settings ships its
# own copy with a Fedora logo and website.
# Only on a real build (no file arguments) or when a test names the path.
if [[ $# -eq 0 || -n "${TUNAOS_KCM_ABOUT:-}" ]]; then
	about="${TUNAOS_KCM_ABOUT:-/etc/xdg/kcm-about-distrorc}"
	mkdir -p "$(dirname "$about")"
	cat >"$about" <<'ABOUT'
[General]
LogoPath=/usr/share/pixmaps/tunaos.svg
Website=https://github.com/tuna-os/tunaos
Variant=part of TunaOS
ABOUT
fi
