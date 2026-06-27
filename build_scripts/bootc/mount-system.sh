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

# shellcheck disable=SC2114
rm -rf /boot /home /root /srv /var /media

mkdir -p \
    /sysroot /boot /usr/lib/ostree /var \
    /home /root /srv /opt /mnt

ln -s sysroot/ostree /ostree
ln -s run/media /media

systemctl enable home.mount mnt.mount opt.mount root.mount srv.mount
