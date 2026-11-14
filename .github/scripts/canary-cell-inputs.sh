#!/usr/bin/env bash
# Read changed paths, one per line; succeed when a PR canary cell input changed
# (TUNA-2): a top-level Containerfile*, anything under build_scripts/, or
# tunaos.toml. Narrower than tuna-pr-build-inputs.sh on purpose: the canary
# cells build desktop images, so they run only when the image recipe changes.
# Keep this boolean independent of the Tuna variant subset: any matching path
# still runs all four family canaries, even a variant-local Containerfile edit.
# The one carve-out is a tunaos.toml edit that tunaos-config-scope.py proves
# touches only [iso_delivery] (ISO cutover/retention lists, which no pull-request
# build reads); it needs TUNA_PR_BASE_SHA, and without it the path still matches.
set -eu

here="$(dirname "${BASH_SOURCE[0]}")"

while IFS= read -r path || [[ -n "$path" ]]; do
	case "$path" in
	tunaos.toml)
		if [[ -n "${TUNA_PR_BASE_SHA:-}" && "$(python3 "$here/tunaos-config-scope.py")" == iso-only ]]; then
			continue
		fi
		printf 'Canary cell input changed: %s\n' "$path"
		exit 0
		;;
	Containerfile* | build_scripts/*)
		printf 'Canary cell input changed: %s\n' "$path"
		exit 0
		;;
	esac
done

exit 1
