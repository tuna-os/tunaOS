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
