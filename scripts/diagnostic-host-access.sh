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
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

cleanup() {
	local failed=0
	if [[ -f "$state/modules.acl" ]]; then
		python3 "$script_dir/diagnostic-acl.py" --sudo restore --snapshot "$state/modules.acl" && rm -f "$state/modules.acl" || failed=1
	fi
	if [[ -f "$state/kernel.acl" ]]; then
		python3 "$script_dir/diagnostic-acl.py" --sudo restore --snapshot "$state/kernel.acl" && rm -f "$state/kernel.acl" || failed=1
	fi
	if ((failed == 0)); then
		rmdir "$state" 2>/dev/null || failed=1
	fi
	return "$failed"
}

grant_module_acl() {
	local unreadable
	unreadable="$(find "$modules" -type f ! -readable -print -quit)" ||
		refuse 'cannot inspect exact supermin module tree'
	[[ -n "$unreadable" ]] || return 0
	python3 "$script_dir/diagnostic-acl.py" --sudo grant --uid "$runner_uid" \
		--path "$modules" --snapshot "$state/modules.acl" ||
		refuse 'cannot grant runner-only access to the exact supermin module tree'
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
			python3 "$script_dir/diagnostic-acl.py" --sudo grant --uid "$runner_uid" \
				--path "$kernel" --snapshot "$state/kernel.acl" ||
				refuse 'cannot grant runner-only access to the exact supermin kernel'
		fi
		grant_module_acl
		[[ -r "$kernel" && -r "$modules" && -x "$modules" ]] || refuse 'supermin inputs remain unreadable to the runner'
		unreadable="$(find "$modules" -type f ! -readable -print -quit)" || refuse 'cannot validate module-tree readability'
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
