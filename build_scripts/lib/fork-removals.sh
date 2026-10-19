#!/usr/bin/env bash
# Qualification candidate only. Normal fork builds reject removals before here.
# Never use the legacy pkg_remove: pacman masks errors; Portage only deselects.

_tunaos_fork_removal_error() {
	printf 'fork removals: %s\n' "$*" >&2
	return 1
}

tunaos_qualify_fork_removals() (
	[[ "${TUNAOS_FORK_REMOVAL_QUALIFICATION:-}" == 1 ]] || {
		_tunaos_fork_removal_error 'requires an explicit disposable qualification environment'
		return 1
	}
	local manager="$1" package installed_name
	shift
	(($# > 0)) || return 0
	case "$manager" in
	dnf | zypper | apt | pacman) ;;
	*)
		_tunaos_fork_removal_error "unsupported removal manager: $manager"
		return 1
		;;
	esac
	# Deliberately conservative, non-overridable policy. Dependency refusal
	# supplements this list; it does not protect leaf boot/network packages.
	for package in "$@"; do
		[[ "$package" =~ ^[A-Za-z0-9][A-Za-z0-9+_.-]*$ ]] || {
			_tunaos_fork_removal_error "not an exact native package name: $package"
			return 1
		}
		case "${package,,}" in
		*kernel* | linux* | *firmware* | *systemd* | *udev* | *boot* | *grub* | shim* | dracut* | initramfs* | mkinitcpio* | *network* | *resolved* | *dhcp* | *wpa* | *iwd* | *connman* | *wicked* | *cryptsetup* | *lvm* | *mdadm* | *btrfs* | *e2fs* | *xfs* | *selinux* | *apparmor* | *policycoreutils* | *polkit* | *pam* | *sudo* | *shadow* | *passwd* | *ssh* | *openssl* | *gnutls* | *ca-certificates* | *keyring* | *dbus* | *glibc* | libc* | *musl* | bash* | coreutils* | util-linux* | filesystem* | base-files* | rpm* | dnf* | dpkg* | apt* | pacman* | zypper* | portage*)
			_tunaos_fork_removal_error "protected boot/network/security/system package: $package"
			return 1
			;;
		esac
	done
	# Query every target first: absent packages must not be reported removed.
	# No recursive dependency cleanup, force, wildcard or solver erase flags.
	case "$manager" in
	dnf | zypper)
		# RPM also accepts version/architecture selectors. Refuse any query
		# that does not resolve to exactly the requested installed name.
		for package in "$@"; do
			installed_name="$(rpm -q --qf '%{NAME}\n' -- "$package")" || return 1
			[[ "$installed_name" == "$package" ]] || {
				_tunaos_fork_removal_error "RPM selector is not one exact installed package name: $package"
				return 1
			}
		done
		rpm -e --test -- "$@" || return 1
		rpm -e -- "$@" || return 1
		;;
	apt)
		for package in "$@"; do
			[[ "$(dpkg-query -W -f='${db:Status-Status}' -- "$package")" == installed ]] || return 1
		done
		dpkg --dry-run --remove -- "$@" || return 1
		dpkg --remove -- "$@" || return 1
		;;
	pacman)
		pacman -Q -- "$@" >/dev/null || return 1
		pacman -R --noconfirm -- "$@" || return 1
		;;
	esac
)
