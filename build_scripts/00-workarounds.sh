#!/bin/bash

set -xeuo pipefail

MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

# This is a bucket list. We want to not have anything in this file at all.
rm -f /usr/lib/bootc/install/20-rhel.toml
# Enable the same compose repos during our build that the centos-bootc image
# uses during its build.  This avoids downgrading packages in the image that
# have strict NVR requirements.
# curl --retry 3 -Lo "/etc/yum.repos.d/compose.repo" "https://gitlab.com/redhat/centos-stream/containers/bootc/-/raw/c${MAJOR_VERSION_NUMBER}s/cs.repo"
# sed -i \
# 	-e "s@- (BaseOS|AppStream)@& - Compose@" \
# 	-e "s@\(baseos\|appstream\)@&-compose@" \
# 	/etc/yum.repos.d/compose.repo
# cat /etc/yum.repos.d/compose.repo
