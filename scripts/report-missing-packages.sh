#!/usr/bin/env bash
# scripts/report-missing-packages.sh
#
# Pretty-print the wishlist files that `install_available` writes
# during builds at /usr/share/tunaos/missing-on-<image>.txt — i.e.
# packages that were requested in build_scripts/desktop/{kde,niri,gnome,...}.sh
# but didn't resolve against the active DNF repo set.
#
# Two usage modes:
#
# 1. Inside a built image (e.g. via `podman run --rm <image>
#    /usr/lib/tunaos/report-missing-packages.sh`):
#       reads /usr/share/tunaos/missing-on-*.txt
#
# 2. From the host against a podman image:
#       ./scripts/report-missing-packages.sh --image localhost/yellowfin:gnome
#
# Output is markdown-formatted so it's drop-in for a GitHub Actions
# step summary or an issue body.

set -euo pipefail

IMAGE=""
WISHLIST_GLOB="/usr/share/tunaos/missing-on-*.txt"

while [[ $# -gt 0 ]]; do
	case "$1" in
	--image)
		IMAGE="$2"
		shift 2
		;;
	--glob)
		WISHLIST_GLOB="$2"
		shift 2
		;;
	-h | --help)
		sed -n '2,20p' "$0"
		exit 0
		;;
	*)
		echo "Unknown flag: $1" >&2
		exit 1
		;;
	esac
done

if [[ -n "$IMAGE" ]]; then
	# Run ourselves inside the image so the wishlist file globs from
	# the same point of view they were written.
	if ! command -v podman &>/dev/null; then
		echo "ERROR: --image requires podman" >&2
		exit 1
	fi
	exec podman run --rm --entrypoint /bin/bash "$IMAGE" \
		-c "set -euo pipefail; \
		    cat ${WISHLIST_GLOB} 2>/dev/null || echo 'No wishlist files inside ${IMAGE}.'" |
		sed -e 's|^|    |'
fi

# Local mode: gather all wishlist files and emit markdown.
shopt -s nullglob
# shellcheck disable=SC2206  # WISHLIST_GLOB is intentionally word-split for globbing
files=($WISHLIST_GLOB)
shopt -u nullglob

if [[ ${#files[@]} -eq 0 ]]; then
	echo "No missing-package wishlists found at ${WISHLIST_GLOB}."
	exit 0
fi

echo "# Missing-on-EL10 wishlist"
echo
echo "Generated $(date -u +%Y-%m-%dT%H:%M:%SZ) from \`install_available\`'s build-time logs."
echo
echo "These packages were requested by tunaos's build scripts but did not"
echo "resolve against the active DNF repos at build time. Add them to"
echo "\`tuna-os/github-copr\` (or another COPR we control) to bring them"
echo "into EL10 reach."
echo

for f in "${files[@]}"; do
	# Each file is appended-to once per caller, so the same image
	# may have multiple stanzas. Sort+uniq to flatten.
	echo "## $(basename "$f" .txt | sed 's/^missing-on-//')"
	echo
	# Skip our header comment lines and keep just package names.
	grep -vE '^#|^$' "$f" | sort -u | while read -r pkg; do
		echo "- \`${pkg}\`"
	done
	echo
done
