#!/bin/bash

set -xeuo pipefail

printf "::group:: === 40 Services ===\n"

MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

# Helper function to safely enable a service (ignore if it doesn't exist)
safe_enable() {
	if systemctl list-unit-files "$1" &>/dev/null || [[ -f "/usr/lib/systemd/system/$1" ]]; then
		systemctl enable "$1" || true
	fi
}

# Helper function to safely disable a service (ignore if it doesn't exist)
safe_disable() {
	if systemctl list-unit-files "$1" &>/dev/null || [[ -f "/usr/lib/systemd/system/$1" ]]; then
		systemctl disable "$1" || true
	fi
}

sed -i 's|uupd|& --disable-module-distrobox|' /usr/lib/systemd/system/uupd.service

# Enable sleep then hibernation by DEFAULT!
sed -i 's/#HandleLidSwitch=.*/HandleLidSwitch=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
sed -i 's/#HandleLidSwitchDocked=.*/HandleLidSwitchDocked=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
sed -i 's/#HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
sed -i 's/#SleepOperation=.*/SleepOperation=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
safe_enable brew-setup.service
if [[ "${DESKTOP_FLAVOR}" == "kde" ]]; then
	safe_disable gdm.service
	safe_enable sddm.service
elif [[ "${DESKTOP_FLAVOR}" == "niri" || "${DESKTOP_FLAVOR}" == "cosmic" ]]; then
	safe_disable gdm.service
	safe_enable greetd.service
elif [[ "${DESKTOP_FLAVOR}" == "gnome" || "${DESKTOP_FLAVOR}" == "gnome50" ]]; then
	safe_enable gdm.service
else
	echo "Skipping DE-specific display-manager service setup (DESKTOP_FLAVOR='${DESKTOP_FLAVOR}')"
fi
safe_enable fwupd.service
safe_enable rpm-ostree-countme.service
systemctl --global enable podman-auto-update.timer
safe_enable rpm-ostree-countme.service
safe_disable rpm-ostree.service
safe_enable dconf-update.service
safe_disable mcelog.service
safe_enable tailscaled.service
safe_enable uupd.timer
safe_enable ublue-system-setup.service
systemctl --global enable ublue-user-setup.service
systemctl mask bootc-fetch-apply-updates.timer bootc-fetch-apply-updates.service
safe_enable check-sb-key.service

# Disable lastlog display on previous failed login in GDM (This makes logins slow)
authselect enable-feature with-silent-lastlog

# Enable polkit rules for fingerprint sensors via fprintd
authselect enable-feature with-fingerprint

if [[ -f /usr/lib/systemd/system/systemd-resolved.service ]]; then
	sed -i -e "s@PrivateTmp=.*@PrivateTmp=no@g" /usr/lib/systemd/system/systemd-resolved.service
	# FIXME: this does not yet work, the resolution service fails for somer reason
	# enable systemd-resolved for proper name resolution
	systemctl enable systemd-resolved.service
fi

printf "::endgroup::\n"
