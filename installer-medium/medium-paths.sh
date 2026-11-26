#!/usr/bin/env bash
# Where /var of the deployed system is on a mounted medium root (tunaOS#4907).
#
# Source this file. The mounted root of an ostree or composefs medium is the
# sysroot, not the deployment: the system's /var is ostree/deploy/<name>/var
# or state/deploy/<id>/var. A file under ROOT/var never shows in the booted
# system. frontends/*/frontend-common.sh resolves the same paths for the
# native frontends.

# medium_var_dir ROOT: print the directory that the booted system sees as
# /var. More than one deployment is an error: the medium holds one.
medium_var_dir() {
	local root="${1%/}" found=() path
	for path in "${root}"/ostree/deploy/*/var "${root}"/state/deploy/*/var; do
		[[ -d "${path}" ]] && found+=("${path}")
	done
	case ${#found[@]} in
	0) printf '%s\n' "${root}/var" ;;
	1) printf '%s\n' "${found[0]}" ;;
	*)
		echo "medium-paths: ${#found[@]} deployments under ${root}: ${found[*]}" >&2
		return 1
		;;
	esac
}
