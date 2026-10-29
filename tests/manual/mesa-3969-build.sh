#!/usr/bin/env bash
# Source-only authoring is safe; execution is one admitted manual CI run only.
set -euo pipefail

SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
[[ "$SCRIPT_DIR" != "${BASH_SOURCE[0]}" ]] || SCRIPT_DIR=.
CORE="$SCRIPT_DIR/mesa_3969.py"
PACKAGES="$SCRIPT_DIR/mesa_3969_packages.py"

case "${1:-}" in
--plan)
	[[ $# -eq 1 ]] || exit 2
	# Only the immutable-input reader is reached: no files, tools or live API.
	exec python3 "$CORE" inputs
	;;
"") [[ $# -eq 0 ]] || exit 2 ;;
*)
	printf 'usage: %s [--plan]\n' "$0" >&2
	exit 2
	;;
esac

# This live producer admission precedes directory creation and all build effects.
PRODUCER="$(python3 "$CORE" producer --job-name 'Build signed Mesa pair')"
ROOT="$(python3 "$CORE" init-root --role build)"
cleanup_private_work() {
	local status=$?
	trap - EXIT
	if ! python3 "$CORE" cleanup-child --role build --child work; then
		printf 'ERROR: marker-bound build work cleanup failed\n' >&2
		status=1
	fi
	exit "$status"
}
trap cleanup_private_work EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Paths are emitted only after admission. Final workflow cleanup owns this root.
printf 'transfer_path=%s/transfer\nevidence_path=%s/evidence\n' "$ROOT" "$ROOT" >>"${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
mkdir -m 0700 "$ROOT/work"
printf '%s\n' "$PRODUCER" >"$ROOT/work/producer.json"
python3 "$PACKAGES" build --root "$ROOT" --producer "$ROOT/work/producer.json"
