#!/usr/bin/env bash
set -euo pipefail

refuse() {
	echo "::error::Diagnostic host access refused: $*" >&2
	exit 77
}

kernel="/boot/vmlinuz-$(uname -r)"
modules="/usr/lib/modules/$(uname -r)"
runner_uid="$(id -u)"
state="${RUNNER_TEMP:-/tmp}/tunaos-diag-host-access-${runner_uid}"

remove_acl() {
	local path="$1" acl
	[[ -e "$path" ]] || return 1
	acl="$(sudo -n getfacl -cp -- "$path")" || return 1
	if [[ "$acl" == *"user:${runner_uid}:"* ]]; then
		sudo -n setfacl -x "u:${runner_uid}" -- "$path"
	fi
}

cleanup() {
	local path failed=0
	if [[ -f "$state/modules" ]]; then
		[[ -d "$modules" ]] || return 1
		while IFS= read -r -d '' path; do
			remove_acl "$path" || failed=1
		done < <(find "$modules" -xdev ! -type l -print0)
	fi
	if [[ -f "$state/kernel" ]]; then
		remove_acl "$kernel" || failed=1
	fi
	rm -f "$state/modules" "$state/kernel"
	rmdir "$state" 2>/dev/null || failed=1
	return "$failed"
}

grant_module_acl() {
	local unreadable acl
	unreadable="$(find "$modules" -type f -name '*.ko*' ! -readable -print -quit)" ||
		refuse 'cannot inspect exact supermin modules'
	[[ -n "$unreadable" ]] || return 0
	acl="$(sudo -n getfacl -R -cp -- "$modules")" || refuse 'cannot inspect the exact supermin module-tree ACLs'
	[[ "$acl" != *"user:${runner_uid}:"* ]] || refuse 'pre-existing runner ACLs in the supermin module tree prevent safe cleanup'
	: >"$state/modules"
	sudo -n setfacl -n -R -m "u:${runner_uid}:rX" -- "$modules" ||
		refuse 'cannot grant runner-only read/traverse access to the exact supermin module tree'
}

main() {
	case "${1:-}" in
	prepare)
		[[ "$runner_uid" != 0 ]] || refuse 'must run as the non-root runner'
		command -v setfacl >/dev/null && command -v getfacl >/dev/null || refuse 'ACL tools are unavailable'
		sudo -n true || refuse 'non-interactive sudo is unavailable'
		[[ -c /dev/kvm ]] || refuse '/dev/kvm is unavailable'
		getent group kvm >/dev/null || refuse 'kvm group is unavailable'
		[[ "$(stat -c '%G' /dev/kvm)" == kvm ]] || refuse '/dev/kvm is not owned by the kvm group'
		kvm_mode="$(stat -c '%a' /dev/kvm)"
		(((8#$kvm_mode & 0060) == 0060)) || refuse '/dev/kvm does not grant group read/write; no device-mode change is allowed'
		[[ -r /sys/fs/cgroup/cgroup.controllers ]] || refuse 'cgroup v2 is unavailable'
		systemctl --version >/dev/null || refuse 'systemd is unavailable'
		[[ -f "$kernel" && -d "$modules" ]] || refuse 'the exact host kernel or module tree is unavailable'
		[[ ! -e "$state" ]] || refuse 'stale temporary ACL state exists'
		umask 077
		mkdir "$state"
		trap 'status=$?; if ((status)); then trap - EXIT; cleanup || echo "::error::Temporary supermin ACL cleanup failed" >&2; fi; exit "$status"' EXIT
		if [[ ! -r "$kernel" ]]; then
			acl="$(sudo -n getfacl -cp -- "$kernel")" || refuse 'cannot inspect the exact supermin kernel ACL'
			[[ "$acl" != *"user:${runner_uid}:"* ]] || refuse 'pre-existing runner ACL on the supermin kernel prevents safe cleanup'
			: >"$state/kernel"
			sudo -n setfacl -m "u:${runner_uid}:r" -- "$kernel" || refuse 'cannot grant runner-only access to the exact supermin kernel'
		fi
		grant_module_acl
		[[ -r "$kernel" && -r "$modules" && -x "$modules" ]] || refuse 'supermin inputs remain unreadable to the runner'
		unreadable="$(find "$modules" -type f -name '*.ko*' ! -readable -print -quit)" || refuse 'cannot validate module-tree readability'
		[[ -z "$unreadable" ]] || refuse 'some exact supermin modules remain unreadable to the runner'
		trap - EXIT
		;;
	cleanup)
		[[ -d "$state" ]] || exit 0
		cleanup || refuse 'temporary supermin ACL cleanup failed'
		;;
	*)
		refuse 'expected prepare or cleanup'
		;;
	esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	main "$@"
fi
