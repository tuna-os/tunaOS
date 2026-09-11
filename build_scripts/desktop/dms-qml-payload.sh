#!/usr/bin/env bash
# Ensure the DMS (DankMaterialShell) QML payload is on the image whenever
# greetd is going to launch dms-greeter.
#
# Why this exists as a post_install hook and not as a call inside niri.sh.
# niri.sh is the LEGACY per-desktop installer. Every variant that ships niri
# today takes the manifest path instead (manifests/desktops/niri.yaml →
# install-desktop.sh), and that path never sources niri.sh — so the fallback
# niri.sh calls has never once run on a variant that needed it. The result was
# measured on 2026-09-11, identically on albacore, skipjack and yellowfin:
#
#   FAIL: greetd launches dms-greeter but
#         /usr/share/quickshell/dms-greeter/DMSGreeter.qml is missing
#   FAIL: no wallpaper daemon (swaybg/swww/wpaperd) and no dms
#   TUNAOS_BRANDING_NIRI_FAIL failures=2
#
# — two failures, one cause, and the niri image build died after three
# attempts on all three variants (runs 34573957352, 34483960197, 34563335220).
# Both assertions in verify-branding-niri.sh read the same directory, which the
# AvengeMedia EL10 dms-greeter 1.6 RPM does not populate: it is a runtime-sync
# launcher that ships no QML, and an image build cannot rely on a first-boot
# download.
#
# Sourced, not executed, by install-desktop.sh — so this file must never
# `exit`. The real installer runs in its own shell for exactly that reason.
#
# Conditioned on the state that is broken rather than on a distro list: if a
# repository ever ships an RPM that owns DMSGreeter.qml, the file is already
# there and this is a no-op (tunaOS#2359). Variants with no DMS at all (Arch's
# marlin, openSUSE's sailfin) have no dms-greeter binary and are skipped —
# their greeters are cosmic-greeter and gtkgreet, and hardcoding DMS paths onto
# them is what reddened marlin:niri before.
if command -v dms-greeter >/dev/null 2>&1 &&
	[[ ! -f /usr/share/quickshell/dms-greeter/DMSGreeter.qml ]]; then
	echo "dms-qml-payload: dms-greeter is installed but ships no QML; installing the pinned payload"
	bash "${_TD_CTX:-/run/context}/build_scripts/install-dms-qml-fallback.sh"
else
	echo "dms-qml-payload: nothing to do (no dms-greeter, or its QML is already present)"
fi
