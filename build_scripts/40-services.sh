#!/bin/bash

set -xeuo pipefail

printf "::group:: === 40 Services ===\n"

MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

source /run/context/build_scripts/lib.sh

# Make sure an SSH server EXISTS on every variant, whatever it is packaged as.
#
# tunaOS#951. openssh-server was installed in exactly one place in this file —
# the apt branch, under ENABLE_SSHD=1. Nothing installed it for pacman or
# zypper at all. The rpm variants only ever worked because their BASE IMAGES
# happen to ship the package, so "sshd closed by default" meant a disabled
# SERVICE there and a MISSING PACKAGE everywhere else.
#
# The consequence was structural, not cosmetic: customize-live.sh:217 needs a
# real unit file to enable when building a dev ISO, and aborts with
#
#   ERROR: dev ISO requested but no SSH service is installed
#
# The dev ISO gates every LUKS and installer cell, so flounder, flounder-sid,
# grouper, marlin and sailfin were not under-exercised in the matrix — they
# were UNBUILDABLE for those axes. That is why LUKS coverage clusters entirely
# on the rpm family; it was a property of this function's absence, not of the
# variants.
#
# Presence-guarded rather than unconditional, so this is a no-op on the rpm and
# gentoo bases that already ship a server: no extra build time, no behaviour
# change, and no new failure mode on images this was never broken for.
ensure_openssh_installed() {
	if [[ -f /usr/lib/systemd/system/sshd.service ]] ||
		[[ -f /usr/lib/systemd/system/ssh.service ]] ||
		[[ -f /lib/systemd/system/sshd.service ]] ||
		[[ -f /lib/systemd/system/ssh.service ]]; then
		echo "openssh already present — nothing to install"
		return 0
	fi
	# Package names differ; the unit does not. Arch calls it plain `openssh`,
	# and Gentoo needs the full atom.
	case "${PKG_MGR:-dnf}" in
	pacman) pkg_install openssh ;;
	emerge) pkg_install net-misc/openssh ;;
	# openSUSE split openssh-server out of openssh; older bases still only
	# have the combined package, so try the split name and fall back.
	zypper) pkg_install openssh-server || pkg_install openssh ;;
	*) pkg_install openssh-server ;;
	esac
}

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
	kde)
		safe_disable gdm.service
		safe_enable "$(kde_dm_unit)"
		;;
	niri | cosmic)
		safe_disable gdm.service
		safe_enable greetd.service
		;;
	gnome) safe_enable gdm.service ;;
	*) echo "No display manager for DESKTOP_FLAVOR='${DESKTOP_FLAVOR}'" ;;
	esac

	# Live readiness marker for e2e testing
	safe_enable tunaos-live-ready.service

	# Security default: sshd closed (live ISOs may re-enable for dev).
	#
	# openssh-server is installed UNCONDITIONALLY, matching the rpm path.
	# The rpm bases already ship it, so on those images "sshd closed" has
	# always meant the SERVICE is disabled. Gating the apt install on
	# ENABLE_SSHD made the apt path do something stricter than the comment
	# claimed — the package was absent entirely — and that is not a harmless
	# extra bit of hardening: customize-live.sh:217 needs a real unit file to
	# enable for a dev ISO, finds none, and aborts with
	#
	#   ERROR: dev ISO requested but no SSH service is installed
	#
	# Every flounder and flounder-sid cell in the 00:36 LUKS sweep died there
	# (runs 30675951080, 30675954952) without reaching the install layer, and
	# the dev ISO gates the installer axis too — so one packaging asymmetry
	# was holding a large share of the never-tested cells on both axes.
	ensure_openssh_installed
	if [[ "${ENABLE_SSHD:-0}" == "1" ]]; then
		# Debian/Ubuntu ship the real unit as ssh.service, with sshd.service a
		# compat symlink that `systemctl enable` refuses to operate on ("linked
		# unit file"). safe_enable swallows that failure, so name both and let
		# the one that exists win — the same fallthrough customize-live.sh does
		# deliberately at :212-216.
		safe_enable sshd.service
		safe_enable ssh.service
		if ! id liveuser &>/dev/null; then
			useradd -m -s /bin/bash -G sudo liveuser
		fi
		echo 'liveuser:live' | chpasswd
	else
		# Now load-bearing rather than belt-and-braces: Debian's
		# openssh-server postinst ENABLES ssh.service on install, so with the
		# unconditional install above, a disable that misses the Debian unit
		# names would ship published flounder images with sshd running. That
		# would turn a build fix into a security regression, which is why both
		# spellings and both socket units are named here.
		safe_disable sshd.service
		safe_disable ssh.service
		safe_disable sshd.socket
		safe_disable ssh.socket
	fi

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
	safe_enable "$(kde_dm_unit)"
elif [[ "${DESKTOP_FLAVOR}" == "niri" || "${DESKTOP_FLAVOR}" == "cosmic" ]]; then
	safe_disable gdm.service
	safe_enable greetd.service
elif [[ "${DESKTOP_FLAVOR}" == "gnome" ]]; then
	safe_enable gdm.service
else
	echo "Skipping DE-specific display-manager service setup (DESKTOP_FLAVOR='${DESKTOP_FLAVOR}')"
fi
# Live readiness marker — safe to enable everywhere (oneshot log line)
# The e2e harness polls the QEMU serial console for TUNAOS_LIVE_READY.
safe_enable tunaos-live-ready.service

# sshd is disabled by default on the installed system. Live ISOs may enable
# it via the ENABLE_SSHD=1 build arg for local dev testing, but production
# installs default closed.
# (Aligned with zirconium-dev/zirconium dd9f2789 — Disable sshd by default.)
#
# This path is not dnf-only: the apt branch above exits early, so everything
# below also runs for pacman, zypper and emerge. marlin (pacman) failed with
# "no SSH service is installed" for exactly that reason — the package was
# never installed for it, only assumed. See ensure_openssh_installed.
ensure_openssh_installed
if [[ "${ENABLE_SSHD:-0}" == "1" ]]; then
	safe_enable sshd.service
	if ! id liveuser &>/dev/null; then
		useradd -m -s /bin/bash -G wheel liveuser
	fi
	echo 'liveuser:live' | chpasswd
else
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
