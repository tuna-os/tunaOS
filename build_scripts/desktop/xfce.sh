#!/usr/bin/env bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

rpmdb_stage2_guard

case "${1:-}" in
"base")
	# ── dnf (RPM) XFCE path ──────────────────────────────────────────
	if [[ "$PKG_MGR" == "dnf" ]]; then
		if [[ $IS_FEDORA == true ]]; then
			# repo.tunaos.org currently ships EL10/x86_64 only, so bonito
			# gets stock Fedora XFCE 4.20 (X11). Switch to the
			# hanthor/xfce-wayland stack once a Fedora chroot is published.
			# NOTE: do NOT install the tuna-os.repo file here — its
			# $releasever baseurl 404s on Fedora with
			# skip_if_unavailable=False, breaking every later transaction.
			dnf_retry -y group install "xfce-desktop"
			dnf_retry -y install \
				xfce4-terminal \
				xfce4-power-manager \
				xfce4-notifyd \
				xfce4-taskmanager \
				xfce4-screenshooter \
				thunar \
				thunar-volman \
				xfce4-pulseaudio-plugin \
				xfce4-clipman-plugin \
				xfce4-whiskermenu-plugin \
				thunar-archive-plugin \
				ristretto \
				mousepad \
				xfce4-dict \
				catfish
		else
			# EL10 (AlmaLinux/CentOS Stream): the hanthor/xfce-wayland port —
			# xfwl4 (Rust/Smithay compositor) plus Wayland-adapted
			# panel/session/xfdesktop/settings/thunar. Packaged from
			# tuna-os/tunaos-packages (formerly github-copr) src/xfce-wayland,
			# served by repo.tunaos.org
			# (EL10 x86_64 only — build-config restricts xfce* platforms).
			# NOTE: the stack is not published yet — the EL10 xfce flavors
			# are commented out in build-config until tunaos-packages#65
			# lands. This branch is the intended install path once it does.
			# URL follows the rename: the github-copr path still resolves only
			# via GitHub's rename redirect (byte-identical content), which a
			# future repo of that name would silently break.
			curl -fsSLo /etc/yum.repos.d/tuna-os.repo \
				https://raw.githubusercontent.com/tuna-os/tunaos-packages/main/contrib/tuna-os.repo

			# xfce4-wayland is the meta package tracking the whole adapted
			# stack (xfwl4, panel, session, xfdesktop, settings, thunar,
			# terminal, plugins…) — install it instead of a hand-rolled list
			# so image contents follow the spec's Requires.
			dnf_retry -y install xfce4-wayland

			# The Default xfwm4 theme xfwl4 needs is provisioned by
			# desktop/xfwm4-theme.sh, listed in xfce.yaml's post_install —
			# NOT here. install-desktop.sh never sources this file for the
			# manifest-driven flavors, so a fix placed here does not run.
			install_available xfwm4

			install_available \
				xfce4-whiskermenu-plugin \
				thunar-volman \
				thunar-archive-plugin \
				ristretto \
				mousepad \
				xfce4-dict \
				catfish
		fi

		# The greeter stack (DM probe, gtkgreet + cage, wayland-sessions
		# fallback, greetd config) moved to desktop/xfce-greeter.sh, listed
		# in xfce.yaml's post_install. It does NOT belong here:
		# install-desktop.sh never sources this file for manifest-driven
		# flavors, so a fix placed here does not run.

		exit 0
	fi
	# ── apt (Debian/Ubuntu) path ─────────────────────────────────────
	if [[ "$PKG_MGR" == "apt" ]]; then
		# xfwl4 (Wayland compositor) is not packaged for Ubuntu; ship the
		# standard X11 XFCE stack with lightdm instead.
		#
		# xserver-xorg is NOT implied by anything else on this list under
		# pkg_install's --no-install-recommends: lightdm only Recommends an
		# X server, and this is an X11 session, so without it lightdm's seat
		# has no display server to spawn. Measured on ubuntu:resolute with
		# exactly this package set (LUKS runs 31215925331/31215923156): the
		# daemon logs "Seat seat0: Can't create display server for greeter"
		# to its own /var/log/lightdm/lightdm.log — nothing to the journal —
		# and exits 1 within a second, crash-looping display-manager.service.
		# The gdm/wayland images never hit this because mutter is its own
		# display server. accountsservice is the same story one notch down:
		# a Recommends of lightdm that every greeter queries for the user
		# list; absent, each start warns "Error getting user list from
		# org.freedesktop.Accounts" before the seat failure kills the daemon.
		pkg_install \
			xserver-xorg \
			accountsservice \
			xfce4-session \
			xfwm4 \
			xfce4-panel \
			xfdesktop4 \
			xfce4-settings \
			xfce4-terminal \
			xfce4-appfinder \
			xfce4-power-manager \
			xfce4-notifyd \
			xfce4-taskmanager \
			xfce4-screenshooter \
			xfce4-pulseaudio-plugin \
			xfce4-whiskermenu-plugin \
			xfce4-clipman-plugin \
			thunar \
			thunar-volman \
			thunar-archive-plugin \
			mousepad \
			ristretto \
			lightdm \
			lightdm-gtk-greeter \
			xdg-desktop-portal-gtk \
			xdg-user-dirs

		systemctl enable lightdm
		exit 0
	fi
	;;
*)
	echo "Usage: $0 base"
	exit 1
	;;
esac
