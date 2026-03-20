#!/usr/bin/env bash

set -xeuo pipefail
printf "::group:: ===Image Cleanup===\n"
source /run/context/build_scripts/lib.sh

# Image cleanup
# Specifically called by build.sh

# The compose repos we used during the build are point in time repos that are
# not updated, so we don't want to leave them enabled.
# dnf config-manager --set-disabled baseos-compose,appstream-compose

dnf clean all

rm -rf /.gitkeep

# Clean up /run artifacts left by dnf/selinux during build (bootc lint: nonempty-run-tmp)
rm -rf /run/dnf /run/selinux-policy

# Clean /var/log dnf artifacts (bootc lint: var-log)
rm -f /var/log/dnf5.log /var/log/dnf5.log.*

# Clean /var but skip mounted directories
find /var -mindepth 1 -maxdepth 1 ! -path '/var/cache' -delete 2>/dev/null || true
find /var/cache -mindepth 1 -delete 2>/dev/null || true

# Declare /var/cache/dnf in tmpfiles.d so it's recreated on first boot (bootc lint: var-tmpfiles)
echo "d /var/cache/dnf 0755 root root - -" >/usr/lib/tmpfiles.d/dnf-cache.conf

mkdir -p /var /boot

# Make /usr/local writeable, if /usr/local exists skip
ls /usr/local || ln -s /var/usrlocal /usr/local

# We need this else anything accessing image-info fails
# FIXME: Figure out why this doesnt have the right permissions by default
chmod 644 /usr/share/ublue-os/image-info.json

# FIXME: use --fix option once https://github.com/containers/bootc/pull/1152 is merged
bootc container lint --fatal-warnings

jq . /usr/share/ublue-os/image-info.json

detected_os

printf "::endgroup::\n"
