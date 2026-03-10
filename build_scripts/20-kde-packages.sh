#!/bin/bash

set -xeuo pipefail

source /run/context/build_scripts/lib.sh

# ublue-os packages
install_from_copr ublue-os/packages \
	ublue-os-just \
	ublue-os-luks \
	ublue-os-signing \
	ublue-os-udev-rules \
	ublue-os-update-services \
	ublue-{motd,bling,rebase-helper,setup-services,polkit-rules,brew} \
	uupd \
	kcm_ublue \
	krunner-bazaar
