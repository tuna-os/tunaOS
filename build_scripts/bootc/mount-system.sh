#!/usr/bin/env bash
# Bootcify: convert the customized Ubuntu rootfs into a composefs-backed bootc
# layout.
#
# This WIPES /var (including /var/lib/dpkg and /var/lib/apt) — apt does NOT work
# after this runs. It must therefore be the LAST customization step in every
# variant's final stage, after all package installs.
#
# /home, /opt, /srv, /mnt, /root become systemd bind-mount units that map to
# /var/<dir> at boot (the .mount units and tmpfiles live in the sandbox overlay).
#
# Adapted from bootc-shindig/ubuntu-bootc-remix.
set -ouex pipefail

# Preserve the dpkg database across the wipe below.
#
# The header above notes that /var/lib/dpkg goes with /var. That is true and
# intended for apt's caches, but it also leaves the shipped image unable to
# say what is installed in it: ghcr.io/tuna-os/grouper:base answers
# `dpkg-query -W` with zero packages, and there is no `status` file anywhere
# in the image. So remora layering, update tooling and support diagnostics are
# all blind on a running grouper box, not just at build time
# (tuna-os/tunaos-packages#135).
#
# Fedora hit exactly this with rpm and moved the database into /usr
# (Changes/RelocateRPMToUsr) — the package database describes /usr, so storing
# it there means it snapshots and rolls back with the image rather than being
# erased with /var. Same move for dpkg. The symlink and the tmpfiles rule keep
# the default path working, so apt/dpkg/dpkg-query need no --admindir.
mkdir -p /usr/lib/sysimage
if [ -d /var/lib/dpkg ]; then
	rm -rf /usr/lib/sysimage/dpkg
	cp -a /var/lib/dpkg /usr/lib/sysimage/dpkg
fi

# shellcheck disable=SC2114
rm -rf /boot /home /root /srv /var /media

# L+ rather than L: replace whatever is at the path, so a /var reset
# re-establishes the link instead of leaving dpkg pointing at an empty dir.
# /var/lib needs creating first — tmpfiles does not build parents for L+.
mkdir -p /usr/lib/tmpfiles.d
printf 'd /var/lib 0755 root root -\nL+ /var/lib/dpkg - - - - ../../usr/lib/sysimage/dpkg\n' \
	>/usr/lib/tmpfiles.d/dpkg-sysimage.conf
mkdir -p /var/lib
ln -sT ../../usr/lib/sysimage/dpkg /var/lib/dpkg

mkdir -p \
	/sysroot /boot /usr/lib/ostree /var \
	/home /root /srv /opt /mnt

ln -s sysroot/ostree /ostree
ln -s run/media /media

systemctl enable home.mount mnt.mount opt.mount root.mount srv.mount
