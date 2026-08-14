#!/usr/bin/env bash
# verify-package-wishlist.sh — fail the build when a best-effort install
# skipped a package nobody declared acceptable to skip.
#
# install_available / apt_install_available record every miss into
# /usr/share/tunaos/missing-on-<image>.txt (lib.sh:record_package_wishlist)
# as a ::warning — loud, but warnings do not fail builds. The result was
# that adding one package name to any install_available list silently made
# it optional everywhere, forever: a typo, a dropped EL10 build, or a repo
# regression all shipped as a green image minus a package.
#
# This gate closes the loop. Every wishlist entry must appear in
# checks/package-miss-allowlist.txt — the committed, reviewed declaration of
# "this package is genuinely nice-to-have and may be absent". A miss outside
# that list fails the build, so the person adding the package decides, in
# the same PR, whether it is optional (allowlist it) or required (package it
# or install it strictly).
#
# Skipped on hummingbird images: their repo is being bootstrapped and the
# gap is expected — it is measured and driven to zero by its own tooling
# (measure-hummingbird-gap.py / the tier build gate), not by this file.
#
# Test hooks:
#   TUNAOS_WISHLIST_DIR        directory holding missing-on-*.txt
#                              (default /usr/share/tunaos)
#   TUNAOS_WISHLIST_ALLOWLIST  allowlist path (default: sibling file)

set -euo pipefail

if [[ "${IS_HUMMINGBIRD:-false}" == "true" ]]; then
	echo "TUNAOS_WISHLIST_SKIPPED reason=hummingbird-bootstrap"
	exit 0
fi

WISH_DIR="${TUNAOS_WISHLIST_DIR:-/usr/share/tunaos}"
ALLOWLIST="${TUNAOS_WISHLIST_ALLOWLIST:-$(dirname "${BASH_SOURCE[0]}")/package-miss-allowlist.txt}"

shopt -s nullglob
wishlists=("${WISH_DIR}"/missing-on-*.txt)
if [[ ${#wishlists[@]} -eq 0 ]]; then
	echo "TUNAOS_WISHLIST_OK misses=0 (no wishlist written — nothing was skipped)"
	exit 0
fi

# The allowlist missing entirely while misses exist is a broken build
# context, not a clean pass — say so rather than failing every package.
if [[ ! -f "$ALLOWLIST" ]]; then
	echo "TUNAOS_WISHLIST_FAIL reason=allowlist-not-found path=${ALLOWLIST}" >&2
	exit 1
fi

# Both files share the format: one package name per line, blank lines and
# `#` comments ignored. Wishlists may repeat a name (several callers can
# miss the same package) — dedupe before judging.
read_names() {
	local line
	while IFS= read -r line; do
		line="${line%%#*}"
		line="${line//[[:space:]]/}"
		[[ -n "$line" ]] && printf '%s\n' "$line"
	done <"$1"
}

declare -A allowed=()
while IFS= read -r name; do
	allowed["$name"]=1
done < <(read_names "$ALLOWLIST")

declare -A seen=()
tolerated=() unexpected=()
for wl in "${wishlists[@]}"; do
	while IFS= read -r name; do
		[[ -n "${seen[$name]:-}" ]] && continue
		seen["$name"]=1
		if [[ -n "${allowed[$name]:-}" ]]; then
			tolerated+=("$name")
		else
			unexpected+=("$name")
		fi
	done < <(read_names "$wl")
done

if [[ ${#tolerated[@]} -gt 0 ]]; then
	echo "allowlisted misses (declared acceptable in $(basename "$ALLOWLIST")):"
	printf '  %s\n' "${tolerated[@]}"
fi

if [[ ${#unexpected[@]} -gt 0 ]]; then
	{
		echo "TUNAOS_WISHLIST_FAIL misses=${#unexpected[@]}"
		echo "These packages were requested, silently skipped as unavailable, and are"
		echo "NOT in checks/package-miss-allowlist.txt:"
		printf '  %s\n' "${unexpected[@]}"
		echo "Either package them (tuna-os/tunaos-packages), install them strictly, or —"
		echo "if they are genuinely optional — add them to the allowlist with a comment."
	} >&2
	exit 1
fi

echo "TUNAOS_WISHLIST_OK misses=${#tolerated[@]} (all allowlisted)"
