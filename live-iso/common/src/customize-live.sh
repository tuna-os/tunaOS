#!/usr/bin/env bash
# customize-live.sh — tacklebox live_customize entrypoint for TunaOS ISOs.
#
# Runs inside a container of the flavor's bootc image before tacklebox
# squashes it (CAP_SYS_ADMIN + network; cwd = this directory). Everything
# here lands in the live squashfs ONLY — installed systems never see it.
# Pattern: projectbluefin/dakota-iso configure-live.sh.
#
# Responsibilities:
#   1. Detect the desktop from the image's session files
#   2. Source the desktop adapter (desktop-<D>.sh): autologin, no-sleep, pinning
#   3. Pre-install the desktop-matched installer Flatpak into the squash
#   4. fisherman symlink + polkit setup so the live session installs
#      without password prompts
#   5. Installer offline-stores config

set -exo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Desktop detection ──────────────────────────────────────────────────────
# TUNA_SESSION_ROOT lets the bats tests point detection at a fake root.
_SR="${TUNA_SESSION_ROOT:-}"
DESKTOP="gnome"
if [[ -f "${_SR}/usr/share/wayland-sessions/plasma.desktop" || -f "${_SR}/usr/share/wayland-sessions/plasmawayland.desktop" ]]; then
	DESKTOP="kde"
elif [[ -f "${_SR}/usr/share/wayland-sessions/niri.desktop" ]]; then
	DESKTOP="niri"
elif [[ -f "${_SR}/usr/share/wayland-sessions/cosmic.desktop" ]]; then
	DESKTOP="cosmic"
elif compgen -G "${_SR}/usr/share/xsessions/xfce*.desktop" >/dev/null ||
	compgen -G "${_SR}/usr/share/wayland-sessions/xfce*.desktop" >/dev/null; then
	DESKTOP="xfce"
fi
echo "customize-live: detected desktop=${DESKTOP}"

case "${DESKTOP}" in
kde) INSTALLER_APP="org.tunaos.InstallerKde" ;;
niri) INSTALLER_APP="org.tunaos.InstallerNiri" ;;
cosmic) INSTALLER_APP="org.tunaos.InstallerCosmic" ;;
xfce) INSTALLER_APP="org.tunaos.InstallerXfce" ;;
# gnome has no TunaOS-branded frontend fork; ship upstream bootc-installer
# directly, fetched the same way projectbluefin/dakota-iso does it (see
# install-flatpaks.sh there) rather than from the tuna-os Flatpak remote.
*) INSTALLER_APP="org.bootcinstaller.Installer" ;;
esac

# Test hook: report detection and stop before any system mutation.
if [[ "${TUNA_DETECT_ONLY:-0}" == "1" ]]; then
	echo "DETECTED ${DESKTOP} ${INSTALLER_APP:-none}"
	exit 0
fi

# ── 1b. Live user ────────────────────────────────────────────────────────────
# No TunaOS image ships livesys-scripts, so nothing creates the account the
# desktop adapters autologin to — bake it into the squash instead (pattern:
# projectbluefin/dakota-iso configure-live.sh). Installed systems never see
# this: live squash only.
#
# uid 1000 is free on *most* bootc images, but not all — grouper ships a
# packaged user there, and the unconditional `--uid 1000` failed the whole
# overlay build with "useradd: UID 1000 is not unique" (exit 4). Ask for
# 1000 when it is free (desktop sessions and flatpak expect it) and let
# useradd pick otherwise; nothing here depends on the exact number.
if ! getent passwd liveuser >/dev/null; then
	# bootc images ship /home as a symlink to var/home, but /var is empty in
	# the container layer, so useradd --create-home follows the symlink to a
	# directory that does not exist and dies:
	#
	#   useradd: cannot create directory /home        (exit 12)
	#
	# That is what actually broke the marlin:kde overlay — misread as a
	# transient registry blob error three separate times, because exit 12 was
	# the only thing surfaced. readlink -f resolves a dangling symlink to its
	# intended target, so this materialises whichever base the image means.
	_home_base="$(readlink -f /home 2>/dev/null || echo /home)"
	mkdir -p "${_home_base}"

	_uid_args=()
	getent passwd 1000 >/dev/null || _uid_args=(--uid 1000)
	useradd --create-home "${_uid_args[@]}" --user-group \
		--comment "Live User" --shell /bin/bash liveuser
fi
passwd --delete liveuser >/dev/null 2>&1 || true

# ── 1c. Live networking ──────────────────────────────────────────────────────
# Server-ish bases (grouper/Ubuntu) ship NetworkManager without enabling it,
# leaving the live env with no DHCP at all (bug #17). Enabling here is a
# no-op on variants that already enable it.
if systemctl list-unit-files NetworkManager.service --no-legend 2>/dev/null | grep -q NetworkManager; then
	systemctl enable NetworkManager.service || true
fi

# ── 2. Desktop adapter (autologin, screen-lock, suspend masking) ─────────────
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/desktop-${DESKTOP}.sh"

# ── 2b. containers-storage: offline payload store (tacklebox-built) ─────────
# tacklebox's BuildOfflineStore() assembles an overlay-driver
# containers-storage graphroot of the payload image into
# LiveOS/store.squashfs.img on the ISO. Mount it at
# /var/lib/superiso-store and register it as an additionalimagestore so
# fisherman (bootcViaContainer path) finds it with a `containers-storage:`
# transport ref instead of pulling the same bytes over the network.
# Pattern: projectbluefin/dakota-iso's configure-live.sh, adapted for
# tacklebox's separate-store format.
#
# Use a oneshot service rather than a .mount unit: the escape encoding
# in mount unit filenames (\\x2d for hyphens) has proven fragile across
# systemd versions. A simple ExecStart=mount is more reliable.
STORE_MOUNT="/var/lib/superiso-store"
mkdir -p "$STORE_MOUNT"
cat >/usr/lib/systemd/system/tunaos-offline-store.service <<'UNITEOF'
[Unit]
Description=Mount tacklebox offline image store
DefaultDependencies=no
Before=local-fs.target
ConditionPathExists=/run/initramfs/live/LiveOS/store.squashfs.img

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/mount -o ro,nodev /run/initramfs/live/LiveOS/store.squashfs.img /var/lib/superiso-store
ExecStop=/usr/bin/umount /var/lib/superiso-store

[Install]
WantedBy=local-fs.target
UNITEOF
mkdir -p /etc/systemd/system/local-fs.target.wants
ln -sf /usr/lib/systemd/system/tunaos-offline-store.service \
	/etc/systemd/system/local-fs.target.wants/tunaos-offline-store.service

# The base image's /etc/containers/storage.conf may not exist in the
# customize container (bootc images ship uninitialized storage), and the
# driver may auto-detect as "btrfs" (EL10 default). The offline store is
# ALWAYS overlay, and additionalimagestores silently ignores stores with
# a different driver. So write the complete primary config.
#
# CORRECTION (tunaOS#881). An earlier version of this comment said "do not
# rely on a storage.conf.d drop-in here", which guarded the wrong direction
# and cost a day of LUKS cells. Writing the primary config is necessary and
# NOT sufficient: containers/storage applies storage.conf.d drop-ins AFTER
# the primary file, and `additionalimagestores` is an array that is REPLACED
# wholesale rather than merged. The base image ships
# /usr/share/containers/storage.conf.d/00-vendor.conf, which sets its own
# additionalimagestores and therefore deletes /var/lib/superiso-store from
# the effective config — while `cat /etc/containers/storage.conf` still
# shows it, which is exactly why this took five hypotheses to find.
# Symptom: `podman images -a` empty on the live root despite the squashfs
# being mounted and a valid overlay graphroot (5493 layer entries).
#
# Hence the drop-in below, and hence it lists BOTH stores: last writer wins
# on an array, so whoever writes last has to enumerate everything, or the
# vendor's own store is what disappears instead.
#
# ...but only the stores that actually exist in this rootfs. The vendor
# store is a Fedora/EL bootc convention; openSUSE (sailfin) ships no
# /usr/lib/containers/storage, and the overlay driver hard-fails on a
# listed store it cannot stat ("overlay: can't stat imageStore dir
# /usr/lib/containers/storage"), which takes down every podman invocation
# in the live root — including fisherman's `podman pull
# containers-storage:<ref>`. Enumerating existing directories only keeps
# the vendor store working where it exists and degrades to the offline
# store alone where it does not.
VENDOR_STORE="/usr/lib/containers/storage"
IMAGE_STORES=("$STORE_MOUNT")
if [[ -d "$VENDOR_STORE" ]]; then
	IMAGE_STORES+=("$VENDOR_STORE")
fi
STORE_LIST="$(printf '"%s", ' "${IMAGE_STORES[@]}")"
STORE_LIST="[${STORE_LIST%, }]"

mkdir -p /etc/containers
cat >/etc/containers/storage.conf <<CONFEOF
[storage]
driver = "overlay"
runroot = "/run/containers/storage"
graphroot = "/var/lib/containers/storage"

[storage.options]
additionalimagestores = ${STORE_LIST}

[storage.options.overlay]
mount_program = "/usr/bin/fuse-overlayfs"
CONFEOF

# Higher-precedence drop-in: /etc drop-ins are applied after /usr/share
# ones, and within a directory in lexical order, so 99- beats the vendor's
# 00-. This is the file that actually decides the effective value.
#
# Chosen over deleting /usr/share/containers/storage.conf.d/00-vendor.conf:
# removing a vendor file makes the live image silently diverge from the
# base, and a base rebuild would restore it without restoring our fix. An
# additive higher-precedence drop-in keeps the vendor's store working (it
# is listed here) and keeps the change visible in one place.
mkdir -p /etc/containers/storage.conf.d
cat >/etc/containers/storage.conf.d/99-tbox-offline-store.conf <<DROPEOF
# Written by tunaOS customize-live.sh — see tunaOS#881.
# Must outrank /usr/share/containers/storage.conf.d/00-vendor.conf, whose
# additionalimagestores REPLACES (not merges with) the primary config's and
# would otherwise drop /var/lib/superiso-store entirely.
# The vendor store is listed too when it exists: array values replace, so
# omitting it here would break the vendor's store the same way.
[storage.options]
additionalimagestores = ${STORE_LIST}
DROPEOF

# DO NOT add /var/lib/superiso-store to /etc/containers/mounts.conf.
#
# An earlier revision did, on the theory that a container gets its /etc from
# the IMAGE and therefore cannot see the store, and that mounts.conf
# "bind-mounts the store into every container podman starts". It does not.
# mounts.conf is containers/common's *subscriptions* mechanism: for a
# directory source it walks the tree, reads every file into memory, and
# writes a full copy into the container's runroot
# (/run/containers/storage/overlay-containers/<id>/userdata/<dest>) before
# bind-mounting that copy. On live media the runroot is a tmpfs, so an entry
# there duplicates the whole payload store into RAM twice over — once as the
# reader's buffers, once as tmpfs pages.
#
# That is what killed sailfin:gnome twice. Run 30730744132: `Out of memory:
# Killed process 2978 (podman) anon-rss:7147396kB` on an 8192 MiB guest, read
# as OCI-copy pressure at the time. Run 30731534696, after the guest grew to
# 10240 MiB and gained swap: `Failed to mount subscriptions, skipping entry in
# /etc/containers/mounts.conf: ... /userdata/var/lib/superiso-store/overlay/
# .../usr/lib/firmware/nvidia/.../gsp-570.144.bin.xz: no space left on
# device`, then the container failed to start at all because /run was full.
#
# It is also unnecessary: fisherman bind-mounts the store itself when a path
# needs it (appendImageStoreArgs in internal/install/bootc.go adds
# `-v /var/lib/superiso-store:/var/lib/superiso-store:ro` plus a generated
# storage.conf), and the composefs path does not need it at all — bootc reads
# the exported OCI layout at /run/fisherman/oci-cache. The storage.conf and
# drop-in above are what the *live root's* podman needs; the container's view
# is fisherman's job.

# Dev/E2E media only: the normal published-image policy keeps SSH disabled.
# tacklebox creates liveuser during boot, so install a oneshot that sets its
# temporary test password after livesys and before the SSH daemon starts.
if [[ -f "${SCRIPT_DIR}/.enable-sshd" ]]; then
	SSH_UNIT=""
	# systemctl enable refuses to operate on a "linked unit file" (a symlink
	# under /usr/lib/systemd/system/, as opposed to an Alias= in [Install]).
	# Debian/Ubuntu's openssh-server ships sshd.service as exactly that kind
	# of compat symlink to the real ssh.service unit — require a real
	# (non-symlink) file so that case falls through to ssh.service below.
	[[ -f /usr/lib/systemd/system/sshd.service && ! -L /usr/lib/systemd/system/sshd.service ]] && SSH_UNIT="sshd.service"
	[[ -z "$SSH_UNIT" && -f /usr/lib/systemd/system/ssh.service ]] && SSH_UNIT="ssh.service"
	if [[ -z "$SSH_UNIT" ]]; then
		echo "ERROR: dev ISO requested but no SSH service is installed" >&2
		exit 1
	fi
	mkdir -p /etc/ssh/sshd_config.d /usr/lib/systemd/system \
		/etc/systemd/system/tunaos-live-ready.service.d
	cat >/etc/ssh/sshd_config.d/90-tunaos-live-e2e.conf <<'EOF'
PasswordAuthentication yes
PermitEmptyPasswords no
EOF
	cat >/usr/lib/systemd/system/tunaos-live-ssh-credentials.service <<EOF
[Unit]
Description=Configure temporary TunaOS live E2E SSH credentials
After=livesys.service
Before=${SSH_UNIT}

[Service]
Type=oneshot
ExecStart=/bin/sh -euxc 'getent passwd liveuser >/dev/null || useradd --create-home --user-group --shell /bin/bash liveuser; echo liveuser:live | chpasswd'
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=${SSH_UNIT}
EOF
	cat >/etc/systemd/system/tunaos-live-ready.service.d/10-ssh-credentials.conf <<'EOF'
[Unit]
Requires=tunaos-live-ssh-credentials.service
After=tunaos-live-ssh-credentials.service
EOF
	systemctl enable tunaos-live-ssh-credentials.service "$SSH_UNIT"

	# fisherman (the LUKS/TPM install backend) runs as root over a
	# non-interactive SSH command, so sudo has no TTY to prompt on. Grant
	# liveuser NOPASSWD sudo — dev/E2E media only, matching
	# projectbluefin/dakota-iso's debug=1 live-env setup (liveuser has
	# NOPASSWD sudo there too). Production images never enable sshd, so
	# liveuser never gets a login there.
	#
	# The drop-in authorises a binary that has to BE there. The Fedora and EL
	# bases ship sudo; the openSUSE, Ubuntu and Debian ones do not, and a
	# sudoers file granting rights to a missing binary is completely silent —
	# the ISO builds, the live image boots, and every `sudo` iso-e2e.sh runs in
	# the guest fails with
	#
	#   bash: line 1: sudo: command not found
	#
	# killing the run at `sudo podman load` with no clue where it came from.
	# That was defect 3 of tunaOS#953 on sailfin, fixed by naming sudo in
	# Containerfile.opensuse — and it came back on grouper because the apt
	# bases never got the same line. Assert it here instead, where the
	# assumption is actually made, so the next base to omit sudo fails the ISO
	# build rather than a 20-minute E2E cell.
	if ! command -v sudo >/dev/null 2>&1; then
		echo "ERROR: ENABLE_SSHD=1 grants liveuser NOPASSWD sudo, but this image has no sudo." >&2
		echo "       Add it to this variant's Containerfile base package list." >&2
		exit 1
	fi
	mkdir -p /etc/sudoers.d
	echo 'liveuser ALL=(ALL) NOPASSWD: ALL' >/etc/sudoers.d/90-tunaos-live-e2e
	chmod 0440 /etc/sudoers.d/90-tunaos-live-e2e

	# Same shape, one binary over. The storage.conf and drop-in written above
	# exist so that the live root's PODMAN can see the offline store, and a
	# composefs image cannot be installed without one at all: fisherman's
	# bootcDirect shortcut is unavailable there, so bootc runs inside a
	# container podman starts.
	#
	# guppy had skopeo (bootc's containers-image-proxy) and no podman, which
	# looks close enough to be missed. It is not: every store probe answered
	# `sudo: podman: command not found`, the harness read a store that holds the
	# image as empty, and the cell died 2h30m in on the SSH image transfer that
	# is its last resort. guppy:gnome, LUKS run 31134373523.
	#
	# Fatal here rather than a warning, and only on ENABLE_SSHD media, for the
	# same reason as sudo above: this is the dev/E2E ISO, the assumption is made
	# right here, and 10 seconds of ISO build is a better place to learn it than
	# hour three of a matrix cell.
	if ! command -v podman >/dev/null 2>&1; then
		echo "ERROR: this image has no podman, but the offline image store above" >&2
		echo "       is configured for one and the composefs install path runs" >&2
		echo "       bootc inside a container." >&2
		echo "       Add it to this variant's Containerfile base package list." >&2
		exit 1
	fi
fi

# ── 3. Pre-install the installer Flatpak into the live squash ────────────────
# dbus is needed for flatpak's system helper inside the build container.
if [[ -n "${INSTALLER_APP}" ]]; then
	# Minimal containers (grouper/apt in particular) have no locale beyond
	# POSIX/C, which is strictly ASCII. glib's path handling requires a
	# UTF-8-capable locale even for ASCII paths in this codepath — without
	# one, flatpak fails with "Pathname can't be converted from UTF-8 to
	# current locale." C.UTF-8 is a built-in glibc locale, no locale-gen
	# needed, present on both apt and dnf bases.
	export LANG=C.UTF-8
	export LC_ALL=C.UTF-8
	# bootc images intentionally ship an uninitialized machine-id.  Flatpak
	# starts a private D-Bus client during live-image customization, however,
	# and refuses to do so without a valid ID.  This only mutates the ephemeral
	# live squashfs; installed systems still receive their own machine-id.
	# Several bootc bases make /root a symlink into /var, whose target is not
	# mounted in tacklebox's customization container. Give D-Bus/Flatpak a
	# disposable, always-writable home instead of assuming /root exists.
	export HOME=/tmp/tuna-live-customize
	export XDG_CACHE_HOME="${HOME}/.cache"
	mkdir -p "${XDG_CACHE_HOME}" /run/dbus
	if [[ ! -s /etc/machine-id ]] || grep -qx 'uninitialized' /etc/machine-id; then
		rm -f /etc/machine-id
		# systemd-machine-id-setup (core systemd, always present) rather than
		# dbus-uuidgen — some flavors (niri, cosmic) don't pull in the dbus
		# package that ships dbus-uuidgen, but every systemd-based image has
		# systemd-machine-id-setup.
		systemd-machine-id-setup
	fi

	# Modern desktop images ship dbus-broker as the bus implementation and no
	# longer pull in the classic `dbus-daemon` binary (nor dbus-run-session — see
	# the machine-id note above). flatpak still needs a real bus for both the
	# system helper and its session connection, so make sure the binary exists
	# rather than assuming it: every cosmic flavor plus sailfin/grouper/guppy/
	# marlin died here with "dbus-daemon: command not found" (exit 127) while the
	# 20 images that happen to ship it built fine.
	ensure_dbus_daemon() {
		command -v dbus-daemon >/dev/null 2>&1 && return 0
		echo "dbus-daemon missing; installing the classic bus for the customize step"
		if command -v dnf5 >/dev/null 2>&1; then
			dnf5 install -y dbus-daemon || dnf5 install -y dbus
		elif command -v dnf >/dev/null 2>&1; then
			dnf install -y dbus-daemon || dnf install -y dbus
		elif command -v zypper >/dev/null 2>&1; then
			zypper --non-interactive install -y dbus-1-daemon || zypper --non-interactive install -y dbus-1
		elif command -v pacman >/dev/null 2>&1; then
			pacman -Sy --noconfirm --needed dbus
		elif command -v apt-get >/dev/null 2>&1; then
			apt-get update -qq && apt-get install -y --no-install-recommends dbus
		elif command -v apk >/dev/null 2>&1; then
			apk add --no-cache dbus
		fi
		command -v dbus-daemon >/dev/null 2>&1 || {
			echo "ERROR: dbus-daemon unavailable and could not be installed; flatpak preinstall would fail" >&2
			return 1
		}
	}

	# A forked bus OUTLIVES this script. If it inherits this script's stdout
	# and stderr it keeps the build's output pipe OPEN, so a failure below does
	# not end the build -- it wedges whatever is reading that pipe.
	#
	# Measured on iso-e2e run 32866334376 (hummingbird:base): ensure_flatpak
	# printed its error and exited 1 at 15:35:46, and the step then produced not
	# one further line until the 60-minute timeout killed it at 16:32:26. Three
	# and a half minutes of correct, specific diagnosis became an hour of dead
	# air, and the failure GitHub reported was "has timed out after 60 minutes"
	# rather than "flatpak not installed".
	#
	# The cost is more than a confusing message: build_artifacts_s2 allows an
	# ISO cell 90 minutes, so ANY failure below this line -- today's missing
	# flatpak, or whatever fails next once flatpak lands -- burns the cell's
	# whole budget and then misattributes itself to a timeout.
	#
	# Two changes, and the redirection is the load-bearing one. Sending the
	# daemons' output to /dev/null means they cannot hold the pipe no matter how
	# long they live. The pidfiles are hygiene on top: reap them on the way out
	# rather than leaving buses running in the layer.
	#
	# Deliberately NOT `--print-pid` through a command substitution: `$( )` waits
	# for the pipe to close, which is the very thing a forked daemon holds, so
	# capturing the pid that way hangs the script AT THE FORK -- earlier and
	# harder than the bug being fixed. That is not hypothetical; it is what the
	# first version of this did, and tests/test_a_failing_live_customize_fails_fast.py
	# caught it.
	_live_bus_pidfiles=()
	_reap_live_buses() {
		local _f _pid
		for _f in ${_live_bus_pidfiles[@]+"${_live_bus_pidfiles[@]}"}; do
			[[ -s "$_f" ]] || continue
			read -r _pid <"$_f" || continue
			[[ -n "${_pid//[!0-9]/}" ]] || continue
			kill "$_pid" 2>/dev/null || true
		done
	}
	trap _reap_live_buses EXIT

	#
	# And NOT `--pidfile=FILE` either: dbus-daemon has no such option. Its
	# only pidfile switch is `--nopidfile`; a pidfile path is config-file
	# syntax. `dbus-daemon --fork --pidfile=/x` is a usage error, exit 1,
	# with the usage text on the stderr this helper discards -- so the
	# first version of THIS fix started no bus at all, and every live
	# customize since 2026-08-25 died here (runs 32875192246, 33594824101;
	# the fake bus in tests/test_a_failing_live_customize_fails_fast.py
	# honoured the option the real binary rejects). `--print-pid=3` writes
	# the daemon's pid to fd 3, which is opened on the pidfile: a file, not
	# a pipe, so nothing waits on it and nothing holds it open.
	_start_bus() {
		local _pidfile="$1"
		shift
		_live_bus_pidfiles+=("$_pidfile")
		dbus-daemon "$@" --fork --nopidfile --print-pid=3 3>"$_pidfile" >/dev/null 2>&1
	}

	mkdir -p /var/lib/dbus
	ln -sf /etc/machine-id /var/lib/dbus/machine-id
	ensure_dbus_daemon
	_start_bus /tmp/live-system-bus.pid --system || true

	# grouper (Ubuntu/apt) and bonito-rawhide (Fedora/dnf) don't ship flatpak
	# in their base image, so the pre-install below always died with "flatpak
	# not installed" (tunaOS#1397). Same failure shape as ensure_dbus_daemon
	# above: try the flatpak package on whichever package manager is present
	# before giving up, rather than failing every live-customize run for
	# these bases outright. Portage (guppy/Gentoo) is deliberately not in this
	# list — emerge is a compile-from-source install with no timeout budget
	# here and no precedent in this file; guppy keeps failing loud below until
	# someone verifies an emerge-based install is safe to add.
	ensure_flatpak() {
		command -v flatpak >/dev/null 2>&1 && return 0
		echo "flatpak missing; installing it for the customize step"
		if command -v dnf5 >/dev/null 2>&1; then
			dnf5 install -y flatpak
		elif command -v dnf >/dev/null 2>&1; then
			dnf install -y flatpak
		elif command -v zypper >/dev/null 2>&1; then
			zypper --non-interactive install -y flatpak
		elif command -v pacman >/dev/null 2>&1; then
			pacman -Sy --noconfirm --needed flatpak
		elif command -v apt-get >/dev/null 2>&1; then
			apt-get update -qq && apt-get install -y --no-install-recommends flatpak
		fi
		command -v flatpak >/dev/null 2>&1
	}

	if ! ensure_flatpak; then
		echo "ERROR: flatpak not installed and could not be installed; cannot pre-install ${INSTALLER_APP}" >&2
		exit 1
	fi
	# openSUSE's CA bundle is generated under /var, while bootc image stages
	# intentionally reset /var. Rebuild it in the live customization container
	# before Flatpak contacts any HTTPS remote; this is a harmless no-op on
	# other bases and prevents curl/Flatpak certificate error 60 on Sailfin.
	if command -v update-ca-certificates >/dev/null 2>&1; then
		update-ca-certificates || echo "WARN: could not regenerate CA bundle"
	fi

	# The installer apps (tuna-os-hosted and upstream bootc-installer alike)
	# declare a GNOME/Freedesktop runtime dependency that isn't published on
	# the tuna-os remote itself — only the apps are. `flatpak install`
	# resolves missing runtime refs from any configured remote, so add
	# flathub here too; without it, install fails with "requires the
	# runtime org.gnome.Platform/... which was not found".
	#
	# The image already ships flathub via /etc/flatpak/remotes.d/ (see
	# build_scripts/26-packages-post.sh), so prefer that locally-baked
	# .flatpakrepo — it needs no network. Only fall back to fetching from
	# dl.flathub.org, and never hard-fail the whole ISO build if flathub is
	# unreachable at build time (e.g. IPv6-only egress on a build host):
	# runtime resolution still has the tuna-os remote + the baked remotes.d.
	if [ -f /etc/flatpak/remotes.d/flathub.flatpakrepo ]; then
		flatpak remote-add --system --if-not-exists flathub \
			/etc/flatpak/remotes.d/flathub.flatpakrepo || true
	else
		flatpak remote-add --system --if-not-exists flathub \
			https://dl.flathub.org/repo/flathub.flatpakrepo ||
			echo "WARN: could not add flathub remote (network?); continuing"
	fi

	# Flatpak also opens a session-bus connection even for a system install.
	# The headless tacklebox container has no DISPLAY, so autolaunch cannot
	# create one; provide an explicit short-lived session bus instead. Spun
	# up directly with dbus-daemon (already required above for the system
	# bus) rather than the dbus-run-session wrapper — some flavors (niri,
	# cosmic) don't pull in the package that ships dbus-run-session.
	SESSION_BUS_SOCK="${HOME}/session-bus.sock"
	_start_bus /tmp/live-session-bus.pid --session --address="unix:path=${SESSION_BUS_SOCK}"
	export DBUS_SESSION_BUS_ADDRESS="unix:path=${SESSION_BUS_SOCK}"
	if [[ "${INSTALLER_APP}" == "org.bootcinstaller.Installer" ]]; then
		# gnome: mirrors projectbluefin/dakota-iso's install-flatpaks.sh —
		# download a release bundle and import it into a throwaway local
		# ostree repo. `flatpak install --bundle` in a container build only
		# creates the installer-origin: remote ref, not the deploy/ ref
		# that `flatpak run`/`flatpak list` need; installing from a local
		# file:// remote goes through the full deploy pipeline.
		#
		# Primary source: the tuna-os/bootc-installer fork's release. It
		# MUST be the fork, not upstream projectbluefin: installer-smoke's
		# readiness assert requires the tuna-installer-ready stamp the fork
		# writes on window map (bootc-installer#7/#8), and the upstream
		# release predates it — smoke run 32408962415's gnome leg had the
		# session and installer process fully up yet failed on exactly the
		# missing stamp. Fallback: tuna-os/tuna-installer, which mirrors
		# the same app ID as a release asset.
		INSTALLER_FLATPAK_FILE="/tmp/bootc-installer.flatpak"
		# A flatpak bundle carries refs for ONE architecture, so the asset has
		# to match the host. The release was x86_64-only and the name carried
		# no arch, so an aarch64 ISO downloaded it, imported
		# app/org.bootcinstaller.Installer/x86_64/master, and then:
		#
		#   error: Nothing matches org.bootcinstaller.Installer in remote
		#          installer-local
		#
		# (gurnard run 32495176056, iso:pantheon linux-arm64.) x86_64 keeps
		# the bare name — every existing consumer fetches that exact URL, and
		# renaming it would break them for no gain. See
		# tuna-os/bootc-installer#25.
		_installer_asset="org.bootcinstaller.Installer.flatpak"
		if [[ "$(uname -m)" != "x86_64" ]]; then
			_installer_asset="org.bootcinstaller.Installer-$(uname -m).flatpak"
		fi
		if ! curl --retry 3 --fail --location --max-time 300 \
			"https://github.com/tuna-os/bootc-installer/releases/latest/download/${_installer_asset}" \
			-o "${INSTALLER_FLATPAK_FILE}" 2>/dev/null; then
			echo "tuna-os/bootc-installer unavailable, falling back to tuna-os/tuna-installer..."
			if ! curl --retry 3 --fail --location --max-time 300 \
				"https://github.com/tuna-os/tuna-installer/releases/latest/download/${_installer_asset}" \
				-o "${INSTALLER_FLATPAK_FILE}"; then
				# Name the arch. Without this the next failure reads as
				# "Nothing matches ... in remote installer-local" three
				# commands later, which looks like a corrupt download rather
				# than an asset that was never published.
				echo "ERROR: no ${_installer_asset} published for $(uname -m)" >&2
				exit 1
			fi
		fi
		INSTALLER_LOCAL_REPO="/tmp/installer-local-repo"
		ostree init --repo="${INSTALLER_LOCAL_REPO}" --mode=archive-z2
		flatpak build-import-bundle "${INSTALLER_LOCAL_REPO}" "${INSTALLER_FLATPAK_FILE}"
		rm -f "${INSTALLER_FLATPAK_FILE}"
		flatpak remote-add --system --no-gpg-verify installer-local "file://${INSTALLER_LOCAL_REPO}"
		# On failure, say WHAT THE REMOTES ACTUALLY OFFER. The error flatpak
		# prints names only what was wanted:
		#
		#   error: The application org.bootcinstaller.Installer/x86_64/master
		#   requires the runtime org.gnome.Platform/x86_64/50 which was not found
		#
		# which reads as "flathub is missing" and is not necessarily that. The
		# flathub remote-add immediately above SUCCEEDED in the run that
		# produced this message.
		#
		# skipjack-gnome failed exactly this way in Live ISOs run 32725309736
		# while yellowfin-gnome installed the same app successfully in
		# installer-smoke run 32704425971 an hour earlier. So the runtime is
		# reachable from some bases and not others, and this message cannot
		# tell those apart. Listing the Platform branches each remote actually
		# carries is what separates "no flathub" from "flathub without //50"
		# from "the app wants a branch nobody publishes yet".
		#
		# Diagnostic only, and only on the failure path: it costs nothing when
		# the install works, and every probe is `|| true` so the diagnostic
		# cannot itself become the failure.
		if ! timeout 900 flatpak install --system --noninteractive installer-local "${INSTALLER_APP}"; then
			echo "---- installer flatpak install FAILED; what the remotes offer:"
			echo "-- configured remotes --"
			flatpak remotes --system --columns=name,url 2>&1 | sed "s/^/     /" || true
			# ASK ABOUT THE ONE REF, DO NOT LIST EVERY REMOTE.
			#
			# The first version of this probe ran a bare
			# `flatpak remote-ls --system`, which pulls the FULL index of
			# every configured remote -- flathub included. In run 32728454277
			# the job was killed during exactly that command:
			#
			#   -- org.gnome/org.kde Platform+Sdk branches visible --
			#   + flatpak remote-ls --system --columns=ref
			#   ##[error]The runner has received a shutdown signal.
			#
			# so the listing never printed and the question stayed open. I had
			# written that every probe was `|| true` and so could not become
			# the failure; `|| true` guards a non-zero exit, not a probe that
			# takes long enough to lose the runner. A diagnostic on an error
			# path has to be cheap or it replaces one unanswered failure with
			# another.
			#
			# remote-info names a single ref and answers the actual question in
			# one round trip: present means the runtime IS reachable and the
			# failure is resolution or ordering; absent means the branch is not
			# published on that remote. Bounded, and per-remote so the answer
			# says WHICH remote was asked.
			echo "-- is the required runtime on each remote? --"
			for _remote in flathub tuna-os; do
				for _rt in org.gnome.Platform//50 org.gnome.Platform//49; do
					printf "     %-10s %-28s " "${_remote}" "${_rt}"
					if timeout 60 flatpak remote-info --system "${_remote}" "${_rt}" \
						>/dev/null 2>&1; then
						echo "PRESENT"
					else
						echo "absent (or remote unreachable)"
					fi
				done
			done
			echo "-- what the app asks for --"
			timeout 60 flatpak remote-info --system installer-local "${INSTALLER_APP}" 2>&1 |
				grep -iE "runtime|sdk|branch" | sed "s/^/     /" || true

			[[ -f "${SCRIPT_DIR}/.enable-sshd" ]] &&
				echo "WARN: installer flatpak install failed; continuing (dev/e2e ISO)" ||
				exit 1
		fi
		flatpak remote-delete --system --force installer-local || true
		rm -rf "${INSTALLER_LOCAL_REPO}"

		# A container-build install (no flatpak-system-helper daemon) creates
		# the deployment directory but omits the 'active' symlink inside the
		# branch directory, leaving the app unreachable to flatpak run/list.
		# Reproduce the symlink a normal installation would create.
		# $(uname -m), not a hardcoded x86_64: flatpak deploys under the
		# host arch, so on aarch64 this globbed a directory that does not
		# exist and the repair below silently did nothing.
		_app_arch_dir="/var/lib/flatpak/app/${INSTALLER_APP}/$(uname -m)"
		for _branch_dir in "${_app_arch_dir}"/*/; do
			_branch_dir="${_branch_dir%/}"
			[[ -d "${_branch_dir}" ]] || continue
			if [[ ! -L "${_branch_dir}/active" ]]; then
				_hash=$(find "${_branch_dir}" -maxdepth 1 -mindepth 1 -type d -printf '%f\n' | head -1)
				if [[ -n "${_hash}" ]]; then
					ln -sfn "${_hash}" "${_branch_dir}/active"
					echo "Created active symlink: ${_branch_dir}/active → ${_hash}"
				fi
			fi
		done
	else
		# The image already ships the tuna-os remote via /etc/flatpak/remotes.d/
		# (build_scripts/desktop/tuna-flatpak-remote.sh) — prefer that
		# locally-baked file (no network) and don't hard-fail the build on a
		# transient tunaos.org miss, mirroring the flathub handling above.
		if [ -f /etc/flatpak/remotes.d/tuna-os.flatpakrepo ]; then
			flatpak remote-add --system --if-not-exists tuna-os \
				/etc/flatpak/remotes.d/tuna-os.flatpakrepo || true
		else
			timeout 120 flatpak remote-add --system --if-not-exists tuna-os \
				https://tunaos.org/flatpak/tuna-os.flatpakrepo ||
				echo "WARN: could not add tuna-os remote (network?); continuing"
		fi
		# timeout: flatpak has no network deadline of its own, and a stalled
		# fetch here is indistinguishable from progress in the build log,
		# because tacklebox does not surface customize output. grouper:cosmic
		# sat in [customize] for 3h52m until the 240-min job cap killed the
		# run (31144135208) — twice, where every other flavor clears this
		# phase in ~2 minutes. Bounded, a stall lands in the WARN arm below on
		# dev/E2E media (which never run this flatpak anyway — the harness
		# installs fisherman via FISHERMAN_OVERRIDE) instead of eating the
		# job. On release media it stays fatal, exactly as before.
		timeout 900 flatpak install --system --noninteractive -y tuna-os "${INSTALLER_APP}" ||
			{ [[ -f "${SCRIPT_DIR}/.enable-sshd" ]] &&
				echo "WARN: installer flatpak install failed or timed out; continuing (dev/e2e ISO)" ||
				exit 1; }
	fi

	# ── 4a. fisherman on the host path ────────────────────────────────────
	# The frontends escalate via `flatpak-spawn --host pkexec
	# /usr/local/bin/fisherman`; expose the flatpak-bundled binary there.
	# `|| true`: this script runs under `set -o pipefail`, so when the installer
	# app directory does not exist (the dev/E2E path above warns and continues
	# instead of installing it) find exits 1, the whole substitution fails, and
	# `set -e` kills the script before the intended warning below — the ISO build
	# then dies with a bare "exit status 1". Keep the lookup non-fatal.
	FISHERMAN_BIN=$(find "/var/lib/flatpak/app/${INSTALLER_APP}" \
		-path '*/files/bin/fisherman' -type f 2>/dev/null | head -1 || true)
	if [[ -n "${FISHERMAN_BIN}" ]]; then
		# `mkdir -p /usr/local/bin` is not safe here. On the ostree/bootc layout
		# /usr/local is a symlink to ../var/usrlocal, and /var/usrlocal does not
		# exist in the image — mkdir -p refuses to create *through* a dangling
		# symlink and dies with the confusing:
		#
		#   mkdir: cannot create directory ‘/usr/local’: File exists
		#
		# which killed the whole ISO build for sailfin:gnome in LUKS run
		# 30522159277. Not every variant has it: sailfin:base and yellowfin:base
		# ship a real /usr/local directory, so this only bites the flavors built
		# on the symlinked layout.
		#
		# readlink -m canonicalises without requiring the path to exist, so this
		# creates /var/usrlocal/bin on the symlinked layout and /usr/local/bin on
		# the plain one. The ln below then resolves through the symlink either way.
		mkdir -p "$(readlink -m /usr/local/bin)"
		ln -sf "${FISHERMAN_BIN}" /usr/local/bin/fisherman
	else
		echo "WARNING: fisherman not found inside ${INSTALLER_APP}" >&2
	fi
fi

# ── 4b. Polkit: passwordless install for the live session ────────────────────
# Policy override (allow_active=yes) + JS rule for liveuser, covering both the
# custom action and generic pkexec (dakota-iso #25 belt-and-suspenders).
mkdir -p /usr/share/polkit-1/actions
cat >/usr/share/polkit-1/actions/org.tunaos.Installer.policy <<'POLICYEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
  "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
  "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <action id="org.tunaos.Installer.install">
    <description>Install TunaOS to a disk</description>
    <message>Authentication is required to install an operating system</message>
    <icon_name>drive-harddisk</icon_name>
    <defaults>
      <allow_any>no</allow_any>
      <allow_inactive>no</allow_inactive>
      <allow_active>yes</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/local/bin/fisherman</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
POLICYEOF

mkdir -p /etc/polkit-1/rules.d
cat >/etc/polkit-1/rules.d/99-live-installer.rules <<'RULESEOF'
polkit.addRule(function(action, subject) {
    if ((action.id === "org.freedesktop.policykit.exec" ||
         action.id === "org.tunaos.Installer.install") &&
            subject.user === "liveuser" && subject.local) {
        return polkit.Result.YES;
    }
});
RULESEOF

# ── 5. Installer offline-stores config ────────────────────────────────────────
# Probe list the frontends read to find embedded OCI stores; missing paths
# are skipped, and the live-ISO self-install path needs no store at all.
mkdir -p /etc/tuna-installer
cat >/etc/tuna-installer/offline-stores <<'STORESEOF'
# OCI store roots probed by the TunaOS installer for offline images.
/usr/share/tuna-installer/oci-store
/var/lib/superiso-store
STORESEOF

# ── 5b. Installer recipe: backend keys, from the image rather than a guess ───
#
# /etc/bootc-installer/recipe.json is what the GUI frontends install FROM. It
# ships three keys that describe the target's on-disk layout —
#
#     "bootloader": "systemd", "composeFsBackend": true, "filesystem": "xfs"
#
# — and until now nothing ever set them per variant. build_scripts/90-image-info.sh
# is the only thing that rewrites that file and it touches branding only
# (distro_name, welcome_title, distro_logo, tour), so every one of the 13
# variants shipped that same hardcoded triple.
#
# It is wrong for the EL10 variants. yellowfin, albacore and skipjack are
# traditional ostree + bootupd + GRUB with composefs explicitly disabled
# (Containerfile.el10 pins `[composefs] enabled = no`), so the GUI was telling
# fisherman to do a composefs/systemd-boot install on three images that cannot
# take one. The headless path never hit this because scripts/iso-e2e.sh probes
# the image and builds its own recipe — which is exactly why LUKS E2E can be
# green on a cell whose GUI install has never once been proven.
#
# WHY HERE and not in 90-image-info.sh, which already owns this file: on EL10
# the prepare-root.conf pin is written AFTER 90-image-info.sh runs
# (Containerfile.el10 — 90-image-info at line 134, the pin at line 156), so a
# probe there reads whatever the upstream base happens to ship. That default
# has already drifted once (tuna-os/wootc#28). By live-ISO customize time the
# payload image is final, which makes this the first point where the answer is
# trustworthy.
#
# Same probe as scripts/lib/common.sh TUNAOS_BACKEND_PROBE_SH, and the order is
# load-bearing for the same reason documented there: bootupd payload first, so
# a SEALED image that still ships bootupd stays on the ostree path.
RECIPE_FILE="/etc/bootc-installer/recipe.json"
if [[ -f "$RECIPE_FILE" ]]; then
	# Fatal on failure, deliberately. An image we cannot classify must not get
	# a guessed recipe: 10 seconds of ISO build is a better place to learn this
	# than hour three of a matrix cell, the same rule the sudo and podman
	# assertions above follow.
	_backend_kv="$(bash "${SCRIPT_DIR}/installer-recipe-backend.sh")"
	_bootloader="$(sed -n 's/^bootloader=//p' <<<"$_backend_kv")"
	_composefs_backend="$(sed -n 's/^composeFsBackend=//p' <<<"$_backend_kv")"
	_filesystem="$(sed -n 's/^filesystem=//p' <<<"$_backend_kv")"

	python3 - "$RECIPE_FILE" "$_bootloader" "$_composefs_backend" "$_filesystem" <<'PYEOF'
import json
import sys

path, bootloader, composefs, filesystem = sys.argv[1:5]
with open(path) as f:
    recipe = json.load(f)
recipe["bootloader"] = bootloader
recipe["composeFsBackend"] = composefs == "true"
recipe["filesystem"] = filesystem
with open(path, "w") as f:
    json.dump(recipe, f, indent=2)
    f.write("\n")
PYEOF

	echo "customize-live: installer recipe bootloader=${_bootloader}" \
		"composefs=${_composefs_backend} filesystem=${_filesystem}"
fi

# ── /var/tmp headroom ─────────────────────────────────────────────────────────
# The live overlay puts /var on a small RAM overlay; bootc needs real space
# in /var/tmp when staging an install (dakota-iso pattern).
cat >/usr/lib/systemd/system/var-tmp.mount <<'UNITEOF'
[Unit]
Description=Large tmpfs for /var/tmp in the live environment

[Mount]
What=tmpfs
Where=/var/tmp
Type=tmpfs
Options=size=8G,nr_inodes=1m

[Install]
WantedBy=local-fs.target
UNITEOF
systemctl enable var-tmp.mount

echo "customize-live: done (desktop=${DESKTOP}, installer=${INSTALLER_APP:-upstream})"
