#!/bin/bash

set -eo pipefail
printf "::group:: === 00-workarounds ===\n"

source /run/context/build_scripts/lib.sh
# This is a bucket list. We want to not have anything in this file at all.
if is_rhel; then rm -f /usr/lib/bootc/install/20-rhel.toml; fi
# Enable the same compose repos during our build that the centos-bootc image
# uses during its build.  This avoids downgrading packages in the image that
# have strict NVR requirements.
if is_centos && ! is_almalinux; then
    curl --retry 3 -Lo "/etc/yum.repos.d/compose.repo" "https://gitlab.com/redhat/centos-stream/containers/bootc/-/raw/c${MAJOR_VERSION_NUMBER}s/cs.repo"
    sed -i \
        -e "s@- (BaseOS|AppStream)@& - Compose@" \
        -e "s@\(baseos\|appstream\)@&-compose@" \
        /etc/yum.repos.d/compose.repo
    cat /etc/yum.repos.d/compose.repo
fi


printf "::endgroup::\n"
