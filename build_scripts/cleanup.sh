#!/usr/bin/env bash

set -xeuo pipefail
printf "::group:: ===Image Cleanup===\n"

# Image cleanup
# Specifically called by build.sh

# The compose repos we used during the build are point in time repos that are
# not updated, so we don't want to leave them enabled.
# dnf config-manager --set-disabled baseos-compose,appstream-compose

dnf clean all

rm -rf /.gitkeep
# Clean /var but skip mounted directories and cache that might be in use
find /var -mindepth 1 -maxdepth 1 ! -path '/var/cache' -delete 2>/dev/null || true
find /var/cache -mindepth 1 ! -path '/var/cache/dnf*' -delete 2>/dev/null || true

mkdir -p /var /boot

# Make /usr/local writeable
ln -s /var/usrlocal /usr/local

# We need this else anything accessing image-info fails
# FIXME: Figure out why this doesnt have the right permissions by default
chmod 644 /usr/share/ublue-os/image-info.json

# FIXME: use --fix option once https://github.com/containers/bootc/pull/1152 is merged
bootc container lint --fatal-warnings || true

jq . /usr/share/ublue-os/image-info.json

printf "::endgroup::\n"
