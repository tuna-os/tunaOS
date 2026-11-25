#!/usr/bin/env bash
# Stage the intended ISO E2E diagnostics from a possibly root-owned output
# directory into a runner-owned directory, without chown -R and without
# following links. Safe to run after a cancelled/failed readiness step.
# Usage: stage-iso-e2e-evidence.sh <src-dir> <dest-dir>
# Run as root (sudo) so root-owned inputs are readable; chowns only the
# files it creates in <dest-dir>. Always exits 0 once usage is valid: the
# readiness outcome is carried by the workflow, never by staging.
set -uo pipefail

if [[ $# -ne 2 ]]; then
	echo "usage: $0 <src-dir> <dest-dir>" >&2
	exit 2
fi
src=$1
dest=$2
max_bytes=${STAGE_MAX_FILE_BYTES:-16777216} # 16 MiB per file
max_files=${STAGE_MAX_FILES:-32}
owner_uid=${STAGE_OWNER_UID:-${SUDO_UID:-$(id -u)}}
owner_gid=${STAGE_OWNER_GID:-${SUDO_GID:-$(id -g)}}

rm -rf -- "$dest" 2>/dev/null
mkdir -p -- "$dest" || exit 0
manifest="$dest/staging-manifest.txt"
: >"$manifest"
note() { printf '%s\n' "$*" >>"$manifest"; }

if [[ -L "$src" || ! -d "$src" ]]; then
	note "status=missing-or-link source=$(basename -- "$src")"
	chown -R "$owner_uid:$owner_gid" -- "$dest" 2>/dev/null
	exit 0
fi
# Reject redirected ancestors: the resolved path must equal the lexical one.
if [[ "$(realpath -- "$src")" != "$(realpath -s -- "$src")" ]]; then
	note "status=redirected-ancestor"
	chown -R "$owner_uid:$owner_gid" -- "$dest" 2>/dev/null
	exit 0
fi

staged=0
shopt -s nullglob
for path in "$src"/serial.log "$src"/installed-serial.log \
	"$src"/luks-evidence.log "$src"/live-serial.log \
	"$src"/result.json "$src"/current-phase.txt "$src"/*.ppm "$src"/*.png; do
	name=$(basename -- "$path")
	if [[ -L "$path" ]]; then
		note "rejected-link $name"
		continue
	fi
	[[ -f "$path" ]] || continue
	if ((staged >= max_files)); then
		note "skipped-count-limit $name"
		continue
	fi
	size=$(stat -c %s -- "$path" 2>/dev/null) || {
		note "unreadable $name"
		continue
	}
	if ((size > max_bytes)); then
		# Keep the tail of oversized logs; skip oversized images.
		if [[ "$name" == *.log || "$name" == *.txt ]]; then
			tail -c "$max_bytes" -- "$path" >"$dest/$name" 2>/dev/null &&
				note "truncated-tail $name original=$size" ||
				note "unreadable $name"
			staged=$((staged + 1))
		else
			note "skipped-oversize $name size=$size"
		fi
		continue
	fi
	# head -c bounds the read even if the file grows while copying.
	if head -c "$max_bytes" -- "$path" >"$dest/$name" 2>/dev/null; then
		note "staged $name size=$size"
		staged=$((staged + 1))
	else
		rm -f -- "$dest/$name"
		note "unreadable $name"
	fi
done
note "status=done staged=$staged"
chown -R "$owner_uid:$owner_gid" -- "$dest" 2>/dev/null
exit 0
