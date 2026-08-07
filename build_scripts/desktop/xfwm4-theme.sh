#!/usr/bin/env bash
# xfwl4 aborts at startup without xfwm4's theme DATA:
#
#   thread 'main' panicked at src/core/state.rs:260:74:
#   Failed to load initial config: Failed to find theme named Default
#
# It needs /usr/share/themes/Default/xfwm4/. themerc alone is not enough:
# load_title_textures() propagates its image loads with `?`, so the
# xpm/png/svg assets are load-bearing too.
#
# Nothing on EL10 provides them. xfwm4 is X11 with no EL10 build; the whole
# repo.tunaos.org/xfce tree owns exactly one path under
# /usr/share/themes/Default (xfce4-notifyd's gtk.css), and xfwl4's own
# package ships two files, neither a theme.
#
# This logic first shipped inside build_scripts/desktop/xfce.sh, where it
# NEVER RAN: install-desktop.sh sources only the scripts a manifest names in
# post_install:, and xfce.yaml named just tuna-flatpak-remote.sh. The build
# failed on the same missing path with the fix "merged" — the same
# looks-applied-but-isn't shape as the defect it was fixing. Hence a
# standalone post_install script the manifest actually lists.

set -euo pipefail

if [[ -f /usr/share/themes/Default/xfwm4/themerc ]]; then
	echo "xfwm4-theme: already present, nothing to do"
	return 0 2>/dev/null || exit 0
fi

_xfwm4_ver=4.20.0
_xfwm4_sha=a58b63e49397aa0d8d1dcf0636be93c8bb5926779aef5165e0852890190dcf06
_xfwm4_tar="/tmp/xfwm4-${_xfwm4_ver}.tar.bz2"

curl -fsSLo "$_xfwm4_tar" \
	"https://archive.xfce.org/src/xfce/xfwm4/${_xfwm4_ver%.*}/xfwm4-${_xfwm4_ver}.tar.bz2"
echo "${_xfwm4_sha}  ${_xfwm4_tar}" | sha256sum -c -

mkdir -p /usr/share/themes/Default/xfwm4
# Keep xpm (the base layer load_compose_image reads) alongside png/svg (the
# overlays); drop only the build files.
tar -xjf "$_xfwm4_tar" -C /usr/share/themes/Default/xfwm4 \
	--strip-components=3 --exclude='Makefile*' \
	"xfwm4-${_xfwm4_ver}/themes/default"
rm -f "$_xfwm4_tar"

# Fail loudly here rather than leave it to the desktop-experience gate.
test -f /usr/share/themes/Default/xfwm4/themerc
echo "xfwm4-theme: installed Default theme for xfwl4"
