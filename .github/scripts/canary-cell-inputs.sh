#!/usr/bin/env bash
# Read changed paths, one per line; succeed when a PR canary cell input changed
# (TUNA-2): a top-level Containerfile*, anything under build_scripts/, or
# tunaos.toml. Narrower than tuna-pr-build-inputs.sh on purpose: the canary
# cells build desktop images, so they run only when the image recipe changes.
# Keep this boolean independent of the Tuna variant subset: any matching path
# still runs all four family canaries, even a variant-local Containerfile edit.
set -eu

while IFS= read -r path || [[ -n "$path" ]]; do
	case "$path" in
	Containerfile* | build_scripts/* | tunaos.toml)
		printf 'Canary cell input changed: %s\n' "$path"
		exit 0
		;;
	esac
done

exit 1
