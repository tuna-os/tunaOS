#!/bin/bash

set -xeuo pipefail

printf "::group:: === 40 Services ===\n"

MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export SCRIPTS_PATH
export MAJOR_VERSION_NUMBER

source /run/context/build_scripts/lib.sh

rpmdb_stage2_guard

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
# Make liveuser's home survive the /var wipe.
#
# `useradd -m` creates /var/home/liveuser at BUILD time, and 99-cleanup.sh then
# deletes everything under /var. The bootc-base-dirs tmpfiles entry recreates
# the PARENT (/var/home) at boot and nothing recreates the user's own
# directory, so the live ISO boots with an account whose home does not exist:
#
#   Could not chdir to home directory /var/home/liveuser: No such file or directory
#   scp: dest open "/home/liveuser/fisherman-override": No such file or directory
#
# SSH still authenticates, which is why this presents as a scp failure rather
# than a login failure — sailfin:gnome reached the installer and died handing it
# the fisherman binary (LUKS run 31061836333).
#
# A tmpfiles entry is the fix rather than re-running useradd: /var is stateful
# and recreated per boot by design, so anything under it that the image needs
# has to be declared, not created once at build time.
tunaos_declare_liveuser_home() {
	install -d -m 0755 /usr/lib/tmpfiles.d
	printf 'd /var/home/liveuser 0700 liveuser liveuser -\n' \
		>/usr/lib/tmpfiles.d/tunaos-liveuser-home.conf
	# Also create it now, for anything that runs before the first boot.
	install -d -m 0700 -o liveuser -g liveuser /var/home/liveuser 2>/dev/null || true
}

# Print the privilege-separation directory sshd says it cannot find, if any.
#
# `sshd -t` names the path in its own words — "Missing privilege separation
# directory: /var/empty" — which is the only source that cannot be wrong about
# it: the path is compiled in with --with-privsep-path and no config file can
# move it. $2 is a throwaway host key; see the caller for why it is needed.
#
# `tr -d '\r'` is load-bearing, not tidying: sshd logs to stderr in the SSH
# protocol's line ending, so the message really arrives as "…/var/empty\r\n".
# Measured, not assumed — the first version of this wrote the CR into the
# tmpfiles rule, where it became a path that systemd-tmpfiles never created.
#
# The trailing `|| true` is load-bearing too: this script runs under
# `pipefail`, `sshd -t` exits 255 in exactly the case being detected, and
# `dir="$(...)"` inherits that — so without it the probe does not report the
# missing directory, it kills the build on the line that asks about it.
tunaos_sshd_missing_privsep_dir() {
	"$1" -t -h "$2" 2>&1 | tr -d '\r' |
		sed -n 's/^Missing privilege separation directory: //p' | head -1 || true
}

# Make sshd's privilege-separation directory survive the /var wipe.
#
# sshd chroots an unprivileged child into that directory and refuses to start
# without it. Gentoo's is /var/empty (the acct-user/sshd home), and BOTH wipes
# in this build delete it — bootc/ostree-layout.sh's `rm -rf` and
# 99-cleanup.sh's `find /var -mindepth 1 -maxdepth 1 -delete`. Nothing puts it
# back, so guppy's live ISO boots with
#
#   [FAILED] Failed to start OpenSSH server daemon.
#   See 'systemctl status sshd.service' for details.
#
# and never opens port 22. iso-e2e.sh then logs 21 x "Connection timed out
# during banner exchange" and the cell dies right after
# TUNAOS_LUKS_E2E_INSTALL_STARTED, having never reached fisherman: LUKS run
# 31091141499's guppy:xfce. Everything else in that boot was green — branding
# OK, lightdm active, "failed systemd units: 0" because the contract ran
# before sshd's failure was collected — which is why it reads as a networking
# or port-forward problem rather than a missing directory. Verified in a real
# gentoo/stage3 container at the digest build-config pins: with /var wiped the
# way this build wipes it, `sshd -t` exits 255 on the missing directory; with
# the rule below applied by systemd-tmpfiles, sshd listens and a password
# login as liveuser succeeds.
#
# The directory is asked for, not hardcoded, because it differs per base:
# /usr/share/empty.sshd on Arch and Fedora, /run/sshd on Debian, /var/empty on
# Gentoo. Only a path under /var needs anything — /usr ships with the image,
# and /run is the unit's own RuntimeDirectory, which is also why this must not
# create it (`bootc container lint` rejects a non-empty /run).
tunaos_declare_sshd_privsep_dir() {
	local tmpfiles_dir="${TUNAOS_TMPFILES_DIR:-/usr/lib/tmpfiles.d}"
	# Prefix for the directory this creates, so a test can point it at a
	# fixture tree. Same hook as TUNAOS_SYSROOT in ostree-layout.sh; the path
	# inside the tmpfiles rule is resolved at boot, not here.
	local root="${TUNAOS_SYSROOT:-}"
	local sshd_bin="" candidate keydir dir still_missing

	# /usr/sbin is not on every PATH this script runs under, and a silent skip
	# here would reproduce the defect exactly.
	for candidate in "$(command -v sshd 2>/dev/null || true)" /usr/sbin/sshd /usr/bin/sshd; do
		if [[ -n "$candidate" && -x "$candidate" ]]; then
			sshd_bin="$candidate"
			break
		fi
	done
	if [[ -z "$sshd_bin" ]]; then
		echo "WARNING: no sshd binary found; cannot check its privsep directory" >&2
		return 0
	fi

	# `sshd -t` exits at the first missing host key BEFORE it reaches the
	# privsep check, and the image ships none — sshd.service generates them at
	# boot with `ssh-keygen -A`. Without a throwaway key the probe only ever
	# answers "sshd: no hostkeys available -- exiting." and this would declare
	# nothing while looking like it had checked.
	keydir="$(mktemp -d)"
	if ! ssh-keygen -q -t ed25519 -N '' -f "${keydir}/probe" >/dev/null 2>&1; then
		echo "WARNING: could not generate a probe host key; skipping privsep check" >&2
		rm -rf "$keydir"
		return 0
	fi

	dir="$(tunaos_sshd_missing_privsep_dir "$sshd_bin" "${keydir}/probe")"
	if [[ -z "$dir" ]]; then
		rm -rf "$keydir"
		return 0
	fi
	case "$dir" in
	/var/*) ;;
	*)
		echo "sshd privsep directory ${dir} is outside /var — nothing to declare"
		rm -rf "$keydir"
		return 0
		;;
	esac

	install -d -m 0755 "$tmpfiles_dir"
	printf 'd %s 0755 root root -\n' "$dir" \
		>"${tmpfiles_dir}/tunaos-sshd-privsep.conf"
	# root-owned and not group/world-writable, or sshd rejects it anyway.
	install -d -m 0755 "${root}${dir}"

	# Prove the declaration is the one sshd asked for, here rather than 20
	# minutes into an E2E cell. A bare call under `set -e` makes this fail the
	# build; a warning would be swallowed exactly the way the original failure
	# was.
	still_missing="$(tunaos_sshd_missing_privsep_dir "$sshd_bin" "${keydir}/probe")"
	rm -rf "$keydir"
	if [[ -n "$still_missing" ]]; then
		echo "ERROR: sshd still cannot find its privilege separation directory" >&2
		echo "       (${still_missing}) after declaring ${dir}." >&2
		return 1
	fi
	echo "declared sshd privsep directory ${dir}"
}

# Enable a network manager, or the image boots with a NIC and no address.
#
# Called from BOTH the apt branch and the pacman/zypper/emerge branch. The apt
# branch exits early, so logic placed only in the latter never runs for
# Ubuntu/Debian — which is exactly how grouper:gnome ended up unreachable with
# sshd running and host keys generated (LUKS run 31061486055), the same
# signature sailfin had. flounder passes because Containerfile.debian installs
# network-manager and Ubuntu's base ships nothing; the difference was never
# deliberate.
tunaos_enable_network_manager() {
	local net_unit=""
	if [[ -f /usr/lib/systemd/system/NetworkManager.service ]]; then
		net_unit=NetworkManager.service
	elif [[ -f /usr/lib/systemd/system/systemd-networkd.service ]]; then
		net_unit=systemd-networkd.service
	elif [[ "${PKG_MGR:-}" == "zypper" ]] || command -v zypper &>/dev/null; then
		# openSUSE splits networkd into its own package.
		pkg_install systemd-network
		[[ -f /usr/lib/systemd/system/systemd-networkd.service ]] &&
			net_unit=systemd-networkd.service
	fi

	if [[ -n "$net_unit" ]]; then
		# Explicit, not safe_enable: both openSUSE and Arch ship `disable *`
		# presets, so this is the only thing turning networking on, and a
		# swallowed failure ships an image with no network and no complaint.
		systemctl enable "$net_unit"
		return 0
	fi

	if command -v emerge &>/dev/null; then
		# Gentoo builds from source, so naming an atom here is an unbounded
		# compile rather than a package fetch, and guppy's networking has not
		# been measured the way openSUSE's and Arch's have. Say so instead of
		# guessing, and leave the build passing as it does today.
		echo "WARNING: no network manager on the emerge path; guppy may boot without networking" >&2
		return 0
	fi

	# Last, so a missing stack cannot fall through to a success. `return 1`
	# fails the build because every call site is a bare command under `set -e`
	# — a `|| true`, an `if`, or a `!` would swallow it exactly the way
	# safe_enable swallowed the absent unit that started all this.
	echo "ERROR: no NetworkManager or systemd-networkd unit on this image." >&2
	echo "       It would boot with a NIC and no address, and sshd would" >&2
	echo "       accept the port forward while answering nothing." >&2
	return 1
}

# Enable systemd-resolved, AND connect it to the file glibc actually reads.
#
# Enabling the unit is only half of name resolution. resolved publishes its
# nameserver in /run/systemd/resolve/stub-resolv.conf, glibc reads
# /etc/resolv.conf, and the two are joined by a symlink the image has to ship.
# It does not, and nothing in the build noticed: systemd-resolved's postinst
# tries to create it and cannot, because podman bind-mounts /etc/resolv.conf
# for the duration of the build —
#
#   Converting /etc/resolv.conf to a symlink to /run/systemd/resolve/stub-resolv.conf...
#   ln: failed to create symbolic link '/etc/resolv.conf': Device or resource busy
#
# which is a warning, not a failure. So the image ships the base's 0-byte
# /etc/resolv.conf, resolved answers on 127.0.0.53 that nobody asks, and every
# lookup fails. That is gurnard:pantheon's
#
#   not ok - DNS resolution (ghcr.io)
#   not ok - network connectivity
#
# in LUKS run 31065556710, and why the run could not pull its own image from
# ghcr.io and fell back to pushing 1.6 GB over SSH instead.
#
# The vendor tmpfiles rule meant to cover this cannot, and neither can a copy
# of it: systemd-resolved's own /usr/lib/tmpfiles.d/systemd-resolve.conf spells
# it `L!`, and plain `L` creates a symlink only when nothing is at the path.
# The Ubuntu, Debian and openSUSE bases all ship a 0-byte /etc/resolv.conf, so
# `L!` is a silent no-op on every one of them. `L+!` removes what is there
# first, which is the entire fix. (Containerfile.opensuse has the same `L!`
# no-op, but sailfin runs none of the numbered build_scripts and never enables
# resolved at all, so it needs its own change rather than this one.)
tunaos_enable_systemd_resolved() {
	# Both directories are variables for the same reason /usr/lib/os-release is
	# one in 90-image-info.sh: so a test can run this function against the files
	# it really writes, instead of grepping the source for a rule whose whole
	# defect was that it looked right. Only the write locations are redirected —
	# the paths INSIDE the rule are resolved at boot, not here.
	local unit_dir="${TUNAOS_SYSTEMD_SYSTEM_DIR:-/usr/lib/systemd/system}"
	local tmpfiles_dir="${TUNAOS_TMPFILES_DIR:-/usr/lib/tmpfiles.d}"

	[[ -f "${unit_dir}/systemd-resolved.service" ]] || return 0

	sed -i -e "s@PrivateTmp=.*@PrivateTmp=no@g" "${unit_dir}/systemd-resolved.service"
	systemctl enable systemd-resolved.service

	# Written only here, next to the enable, so the symlink can never point at
	# a stub that nothing populates.
	install -d -m 0755 "$tmpfiles_dir"
	printf 'L+! /etc/resolv.conf - - - - ../run/systemd/resolve/stub-resolv.conf\n' \
		>"${tmpfiles_dir}/tunaos-resolv-conf.conf"
}

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
	# Not gated on ENABLE_SSHD: the published images keep the service off, but
	# an installed system enabling it later needs the same directory, and the
	# rule is one line.
	tunaos_declare_sshd_privsep_dir
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
		tunaos_declare_liveuser_home
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

	tunaos_enable_network_manager

	# Units that exist on Ubuntu once their packages are installed.
	safe_enable tailscaled.service
	safe_enable fwupd.service
	systemctl enable podman-auto-update.timer 2>/dev/null || true

	# systemd-resolved for name resolution.
	tunaos_enable_systemd_resolved

	printf "::endgroup::\n"
	exit 0
fi
# ── pacman / zypper / emerge path ─────────────────────────────────────
# These package managers indicate Arch, openSUSE or Gentoo bases. They share
# the service enablement pattern with the apt path (safe_enable, drop-ins)
# rather than the dnf path (in-place sed on shipped unit files). The dnf
# path below has Fedora/EL-specific tools (uupd, authselect, rpm-ostree,
# ublue-system-setup) that do not exist on these bases.
if [[ "${PKG_MGR:-}" == "pacman" ]] || command -v zypper &>/dev/null || command -v emerge &>/dev/null; then
	# Sleep-then-hibernate via drop-in (no /usr/lib/systemd/logind.conf on some bases)
	mkdir -p /usr/lib/systemd/logind.conf.d
	cat >/usr/lib/systemd/logind.conf.d/10-tunaos-sleep.conf <<-'LOGIND'
		[Login]
		HandleLidSwitch=suspend-then-hibernate
		HandleLidSwitchDocked=suspend-then-hibernate
		HandleLidSwitchExternalPower=suspend-then-hibernate
		SleepOperation=suspend-then-hibernate
	LOGIND

	# Display manager per desktop flavor
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
	*) echo "Skipping DE-specific display-manager service setup (DESKTOP_FLAVOR='${DESKTOP_FLAVOR}')" ;;
	esac

	safe_enable tunaos-live-ready.service

	# SSH handling (matching apt path logic)
	ensure_openssh_installed
	# This is the path guppy takes, and the one the missing /var/empty killed.
	tunaos_declare_sshd_privsep_dir
	if [[ "${ENABLE_SSHD:-0}" == "1" ]]; then
		safe_enable sshd.service
		if ! id liveuser &>/dev/null; then
			useradd -m -s /bin/bash -G wheel liveuser 2>/dev/null || \
			useradd -m -s /bin/bash liveuser 2>/dev/null || true
		fi
		echo 'liveuser:live' | chpasswd
		tunaos_declare_liveuser_home
	else
		safe_disable sshd.service
		safe_disable sshd.socket 2>/dev/null || true
	fi

	# A network manager, or the live ISO has a NIC and no address.
	#
	# sailfin:cosmic reached the live boot with sshd running and ZERO failed
	# units, and the host still could not reach it — "Connection timed out
	# during banner exchange", 21 attempts, then the run gave up. The guest's
	# own contract had already said why:
	#
	#   not ok - a network manager is active
	#   virtio_net virtio4 ens6: renamed from eth0
	#
	# The NIC was there and nothing configured it, so sshd was listening on a
	# machine with no address (LUKS run 31060731552). Nothing on this path
	# enabled a network manager on any of pacman/zypper/emerge.
	#
	# Prefer NetworkManager where it exists, else systemd-networkd — the same
	# either/or the contract itself accepts
	# (checks/e2e-runtime-checks.sh: `is-active NetworkManager || is-active
	# systemd-networkd`). Enabling both invites two daemons managing one link;
	# Containerfile.opensuse already ships a networkd DHCP profile
	# (/usr/lib/systemd/network/20-wired.network) plus the resolved stub
	# symlink, so networkd is the intended stack there and only needed
	# switching on.
	#
	# Except openSUSE ships networkd in a SEPARATE package, so naming the unit
	# was not enough there. Measured in a tumbleweed container, installing what
	# the image installs:
	#
	#   # zypper install systemd            (Containerfile.opensuse's list)
	#   systemd-networkd.service   ABSENT
	#   # zypper install systemd-network
	#   systemd-networkd.service   PRESENT, and `is-enabled` says disabled
	#
	# So on sailfin the unit enabled here did not exist, safe_enable swallowed
	# that with its `|| true`, and the guest still booted with a NIC and no
	# address: 20-wired.network was a DHCP profile with no daemon to read it.
	#
	# Hence install the daemon where the base omits it, and enable it
	# EXPLICITLY. Both bases here disable by default (openSUSE's
	# 99-default-disable.preset, Arch's 99-default.preset are both `disable *`),
	# so this enable is the only thing that turns networking on and a swallowed
	# failure ships an image with no network and no build-time complaint. Arch
	# needs no install: Containerfile.arch has networkmanager in base-no-de,
	# which is built before this script runs.
	tunaos_enable_network_manager

	safe_enable tailscaled.service
	safe_enable fwupd.service
	systemctl --global enable podman-auto-update.timer 2>/dev/null || true
	systemctl --global enable speech-dispatcher.socket 2>/dev/null || true

	# dconf compilation
	safe_enable dconf-update.service
	if command -v dconf &>/dev/null && compgen -G "/etc/dconf/db/*.d/*" >/dev/null 2>&1; then
		dconf update || true
	fi

	# systemd-resolved
	tunaos_enable_systemd_resolved

	printf "::endgroup::\n"
	exit 0
fi
# ── dnf (RPM / Universal-Blue) path continues below ───────────────────

sed -i 's|uupd|& --disable-module-distrobox|' /usr/lib/systemd/system/uupd.service 2>/dev/null || true

# Enable sleep then hibernation by DEFAULT!
if [[ -f /usr/lib/systemd/logind.conf ]]; then
	sed -i 's/#HandleLidSwitch=.*/HandleLidSwitch=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
	sed -i 's/#HandleLidSwitchDocked=.*/HandleLidSwitchDocked=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
	sed -i 's/#HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
	sed -i 's/#SleepOperation=.*/SleepOperation=suspend-then-hibernate/g' /usr/lib/systemd/logind.conf
fi
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
tunaos_declare_sshd_privsep_dir
if [[ "${ENABLE_SSHD:-0}" == "1" ]]; then
	safe_enable sshd.service
	if ! id liveuser &>/dev/null; then
		useradd -m -s /bin/bash -G wheel liveuser
	fi
	echo 'liveuser:live' | chpasswd
	# No-op where the home already survives (yellowfin:gnome passes today), but
	# the /var wipe is common to every base, so declaring it is not conditional
	# on which path happens to have been caught out.
	tunaos_declare_liveuser_home
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
# dconf-update.service compiles /etc/dconf/db/*.d/ keyfiles at boot.
# Compile them NOW so the verify-desktop-experience.sh check passes
# during image build — it sees the build-time state, not first-boot.
if command -v dconf &>/dev/null && compgen -G "/etc/dconf/db/*.d/*" >/dev/null 2>&1; then
	dconf update || true
fi
safe_disable mcelog.service
safe_enable tailscaled.service
safe_enable uupd.timer

# Base boot contract (green criterion 3, GREEN-MASTER-PLAN W3). Every image
# gets the unit — on desktop images it is the multi-user complement to
# tunaos-desktop-contract.service, on base images it is the only boot proof
# there is. The Gate's --contract base mode keys off its serial marker, the
# same way the desktop gate keys off TUNAOS_DESKTOP_CONTRACT_*.
/run/context/build_scripts/checks/verify-base-contract.sh
install -Dm0755 /run/context/build_scripts/checks/verify-base-contract.sh \
	/usr/libexec/tunaos/verify-base-contract
cat >/usr/lib/systemd/system/tunaos-base-contract.service <<'UNIT'
[Unit]
Description=Verify TunaOS base boot contract
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/libexec/tunaos/verify-base-contract --runtime
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT
systemctl enable tunaos-base-contract.service
safe_enable ublue-system-setup.service
systemctl --global enable ublue-user-setup.service
systemctl mask bootc-fetch-apply-updates.timer bootc-fetch-apply-updates.service auditd.service audit-rules.service
safe_enable check-sb-key.service

# Authselect configuration (Fedora/EL-only; guard for safety)
if command -v authselect &>/dev/null; then
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
fi

if [[ -f /usr/lib/systemd/system/systemd-resolved.service ]]; then
	sed -i -e "s@PrivateTmp=.*@PrivateTmp=no@g" /usr/lib/systemd/system/systemd-resolved.service
	# Enable systemd-resolved for proper name resolution.
	# NOTE: Enabling is not sufficient on some images — the service may
	# fail at runtime due to dbus policy or nsswitch configuration.
	# Investigate if resolved consistently fails across all variants.
	systemctl enable systemd-resolved.service
fi

printf "::endgroup::\n"
