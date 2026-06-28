#!/bin/bash

set -xeuo pipefail

printf "::group:: === 40 Services ===\n"

MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

source /run/context/build_scripts/lib.sh

# safe_enable / safe_disable are defined in lib.sh — they're called from
# multiple build scripts, so the definition lives with the other shared
# helpers (install_available, install_from_copr, etc.).

# ── apt (Ubuntu/Debian) path ──────────────────────────────────────────
# 40-services upstream is Universal-Blue/Fedora-specific (uupd, authselect,
# rpm-ostree, ublue-* units, the Fedora /usr/lib/systemd/logind.conf path).
# On Ubuntu we set up only the units that actually exist; safe_enable/
# safe_disable already no-op on missing units.
if [[ "${PKG_MGR:-}" == "apt" ]]; then
	# Sleep-then-hibernate defaults via a logind drop-in (Ubuntu ships no
	# stock /usr/lib/systemd/logind.conf; a drop-in is honoured everywhere).
	mkdir -p /usr/lib/systemd/logind.conf.d
	cat >/usr/lib/systemd/logind.conf.d/10-tunaos-sleep.conf <<-'LOGIND'
		[Login]
		HandleLidSwitch=suspend-then-hibernate
		HandleLidSwitchDocked=suspend-then-hibernate
		HandleLidSwitchExternalPower=suspend-then-hibernate
		SleepOperation=suspend-then-hibernate
	LOGIND

	# Display manager per desktop flavor.
	case "${DESKTOP_FLAVOR}" in
		kde) safe_disable gdm.service; safe_enable sddm.service ;;
		niri | cosmic) safe_disable gdm.service; safe_enable greetd.service ;;
		gnome | gnome50) safe_enable gdm.service ;;
		*) echo "No display manager for DESKTOP_FLAVOR='${DESKTOP_FLAVOR}'" ;;
	esac

	# Security default: sshd closed (live ISOs may re-enable for dev).
	safe_disable sshd.service
	safe_disable sshd.socket 2>/dev/null || systemctl mask sshd.socket || true

	# Units that exist on Ubuntu once their packages are installed.
	safe_enable tailscaled.service
	safe_enable fwupd.service
	systemctl enable podman-auto-update.timer 2>/dev/null || true

	# systemd-resolved for name resolution.
	if [[ -f /usr/lib/systemd/system/systemd-resolved.service ]]; then
		sed -i -e "s@PrivateTmp=.*@PrivateTmp=no@g" /usr/lib/systemd/system/systemd-resolved.service
		systemctl enable systemd-resolved.service
	fi

	printf "::endgroup::\n"
	exit 0
fi
# ── dnf (RPM / Universal-Blue) path continues below ───────────────────

sed -i 's|uupd|& --disable-module-distrobox|' /usr/lib/systemd/system/uupd.service

# Enable sleep then hibernation by DEFAULT!
sed -i 's/#HandleLidSwitch=.*/HandleLidSwitch=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
sed -i 's/#HandleLidSwitchDocked=.*/HandleLidSwitchDocked=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
sed -i 's/#HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
sed -i 's/#SleepOperation=.*/SleepOperation=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
safe_enable brew-setup.service
safe_enable tunaos-var-home-restorecon.service
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
# sshd is disabled by default on the installed system. Live ISOs may enable
# it via ENABLE_SSHD=1 for dev testing, but production installs default closed.
# (Aligned with zirconium-dev/zirconium dd9f2789 — Disable sshd by default.)
if [[ "${ENABLE_SSHD:-0}" != "1" ]]; then
  safe_disable sshd.service
  safe_disable sshd.socket 2>/dev/null || systemctl mask sshd.socket || true
fi

safe_enable fwupd.service
safe_enable rpm-ostree-countme.service
systemctl --global enable podman-auto-update.timer

# Orca and other AT-SPI screen readers expect speech-dispatcher to be
# socket-activatable per user. Fedora 43 used to enable it as part of
# the user preset but the Fedora policy shifted to disabled-by-default;
# enable explicitly so accessibility works out of the box.
# (Ported from ublue-os/aurora 5e9047c5 — feat: enable speech-dispatcher
# by default. Revisit when redhat-systemd-presets PR#4 lands.)
systemctl --global enable speech-dispatcher.socket 2>/dev/null || true
safe_enable rpm-ostree-countme.service
safe_disable rpm-ostree.service
safe_enable dconf-update.service
safe_disable mcelog.service
safe_enable tailscaled.service
safe_enable uupd.timer
safe_enable ublue-system-setup.service
systemctl --global enable ublue-user-setup.service
systemctl mask bootc-fetch-apply-updates.timer bootc-fetch-apply-updates.service auditd.service audit-rules.service
safe_enable check-sb-key.service

# Authselect configuration
if [[ "$IS_FEDORA" == true ]]; then
	# Fedora uses 'local' as the base profile for standard setups
	authselect select local --force
else
	# RHEL/AlmaLinux/CentOS require sssd for GDM/login to function correctly
	authselect select sssd --force
fi

# Disable lastlog display on previous failed login in GDM (This makes logins slow)
authselect enable-feature with-silent-lastlog

# Enable polkit rules for fingerprint sensors via fprintd
authselect enable-feature with-fingerprint

# Cleanup authselect backups and checksum to satisfy bootc lint
rm -rf /var/lib/authselect/backups/*
rm -f /var/lib/authselect/checksum

if [[ -f /usr/lib/systemd/system/systemd-resolved.service ]]; then
	sed -i -e "s@PrivateTmp=.*@PrivateTmp=no@g" /usr/lib/systemd/system/systemd-resolved.service
	# Enable systemd-resolved for proper name resolution.
	# NOTE: Enabling is not sufficient on some images — the service may
	# fail at runtime due to dbus policy or nsswitch configuration.
	# Investigate if resolved consistently fails across all variants.
	systemctl enable systemd-resolved.service
fi

printf "::endgroup::\n"
