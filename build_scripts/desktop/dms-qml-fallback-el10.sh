#!/usr/bin/env bash
# Overlay the checksum-pinned DMS QML payload on EL10 niri builds.
#
# The AvengeMedia EL10 dms-greeter RPM (installed by manifests/desktops/
# niri.yaml's el10.copr section) only ships a runtime-sync launcher — no QML —
# so without this, greetd execs dms-greeter into a blank window and
# /usr/share/quickshell/dms-greeter/DMSGreeter.qml never exists
# (verify-branding-niri.sh's "dms-greeter shell present" check).
#
# build_scripts/install-dms-qml-fallback.sh already does the actual download
# + checksum + install; this file exists only to call it from the live,
# manifest-driven install path and to gate it to EL10. It used to be wired
# into build_scripts/desktop/niri.sh's "base" case instead, which
# install-desktop.sh (the manifest-driven installer every desktop actually
# goes through now) never calls — so the fallback has never run in a real
# build since it was added (tunaOS#2359).
#
# This is sourced by install-desktop.sh via a manifest's post_install list, so
# it must never call `exit` — that would end the whole desktop install
# (see greetd-gtkgreet.sh for the same contract). The underlying script DOES
# call exit, which is why it is run as a subprocess here rather than sourced.
if [[ "${IS_ALMALINUX:-false}" == true || "${IS_ALMALINUXKITTEN:-false}" == true || "${IS_CENTOS:-false}" == true ]]; then
	if ! "${_TD_CTX}/build_scripts/install-dms-qml-fallback.sh"; then
		echo "ERROR: DMS QML fallback failed; niri greeter would ship with no shell" >&2
		return 1
	fi
fi
