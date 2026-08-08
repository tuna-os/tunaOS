#!/usr/bin/env bash

source /usr/lib/ublue/setup-services/libsetup.sh

version-script framework-lts system 1 || exit 0

set -euo pipefail

# VEN_ID and CPU_VENDOR were referenced below without ever being assigned —
# under `set -u` that is an immediate "unbound variable" crash on the very
# first `[[ ... =~ ... ]]` check, on EVERY machine (not just Framework
# hardware, since the crash happens before the vendor check can even
# short-circuit). This is why ublue-system-setup.service showed as failed
# on a plain yellowfin:gnome VM boot with no Framework chassis at all
# (tunaOS#576). user-setup.hooks.d/10-theming.sh already reads VEN_ID
# correctly; CPU_VENDOR mirrors bluefin's equivalent hook.
VEN_ID="$(cat /sys/devices/virtual/dmi/id/chassis_vendor)"
CPU_VENDOR="$(grep "vendor_id" /proc/cpuinfo | uniq | awk -F": " '{ print $2 }')"

# GLOBAL
KARGS=$(rpm-ostree kargs)
NEEDED_KARGS=()
echo "Current kargs: $KARGS"

if [[ $KARGS =~ "nomodeset" ]]; then
	echo "Removing nomodeset"
	NEEDED_KARGS+=("--delete-if-present=nomodeset")
fi

if [[ ":Framework:" =~ :$VEN_ID: ]]; then
	if [[ "GenuineIntel" == "$CPU_VENDOR" ]]; then
		if [[ ! $KARGS =~ "hid_sensor_hub" ]]; then
			echo "Intel Framework Laptop detected, applying needed keyboard fix"
			NEEDED_KARGS+=("--append-if-missing=module_blacklist=hid_sensor_hub")
		fi
	fi
fi

# Bare `$NEEDED_KARGS` (SC2128, previously suppressed) only ever expands
# element 0 — with zero elements that is itself an unbound-variable crash
# under `set -u` (the common case: no karg changes needed at all). Test the
# array's length instead, which is well-defined for zero, one, or many
# elements. Passing `"${NEEDED_KARGS[*]}"` as a single rpm-ostree argument
# was also wrong once there could be more than one entry — each
# --delete-if-present=/--append-if-missing= flag must be its own argv
# entry, not one space-joined string. tunaOS#576.
if [[ "${#NEEDED_KARGS[@]}" -gt 0 ]]; then
	echo "Found needed karg changes, applying the following: ${NEEDED_KARGS[*]}"
	plymouth display-message --text="Updating kargs - Please wait, this may take a while" || true
	rpm-ostree kargs "${NEEDED_KARGS[@]}" --reboot || exit 1
else
	echo "No karg changes needed"
fi

SYS_ID="$(cat /sys/devices/virtual/dmi/id/product_name)"

# FRAMEWORK 13 AMD FIXES
if [[ ":Framework:" =~ :$VEN_ID: ]]; then
	if [[ $SYS_ID == "Laptop 13 ("* ]]; then
		if [[ "AuthenticAMD" == "$CPU_VENDOR" ]]; then
			if [[ ! -f /etc/modprobe.d/alsa.conf ]]; then
				echo 'Fixing 3.5mm jack'
				tee /etc/modprobe.d/alsa.conf <<<"options snd-hda-intel index=1,0 model=auto,dell-headset-multi"
				echo 0 | tee /sys/module/snd_hda_intel/parameters/power_save
			fi
			if [[ ! -f /etc/udev/rules.d/20-suspend-fixes.rules ]]; then
				echo 'Fixing suspend issue'
				echo "ACTION==\"add\", SUBSYSTEM==\"serio\", DRIVERS==\"atkbd\", ATTR{power/wakeup}=\"disabled\"" >/etc/udev/rules.d/20-suspend-fixes.rules
			fi
		fi
	fi
fi
