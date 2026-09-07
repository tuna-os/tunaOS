#!/usr/bin/env bash
# Reject unexpectedly large upstream snapshot refreshes before they are
# committed. The snapshot workflow intentionally keeps a filtered tree in git,
# so this is an admission budget rather than a replacement for reviewing the
# content diff.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SNAPSHOT_DIR="${REPO_ROOT}/_upstream-snapshots"

# Defaults leave room above the current tree (241 files, ~225 KiB) while
# bounding accidental wholesale additions. The workflow sets these explicitly
# so the policy is visible in its logs and can be changed without editing code.
MAX_FILES="${MAX_SNAPSHOT_FILES:-300}"
MAX_BYTES="${MAX_SNAPSHOT_BYTES:-2097152}"
MAX_CHANGED_FILES="${MAX_SNAPSHOT_CHANGED_FILES:-150}"

die() {
	echo "::error::upstream snapshot budget exceeded: $*" >&2
	exit 1
}

[[ -d "${SNAPSHOT_DIR}" ]] || die "${SNAPSHOT_DIR} does not exist"

files=$(find "${SNAPSHOT_DIR}" -type f -print | wc -l)
bytes=$(du -sb "${SNAPSHOT_DIR}" | awk '{print $1}')
changed=$(git status --short --untracked-files=all -- "_upstream-snapshots/" | wc -l)

echo "Snapshot budget: files=${files}/${MAX_FILES}, bytes=${bytes}/${MAX_BYTES}, changed_paths=${changed}/${MAX_CHANGED_FILES}"

(( files <= MAX_FILES )) || die "${files} files exceeds the ${MAX_FILES}-file limit"
(( bytes <= MAX_BYTES )) || die "${bytes} bytes exceeds the ${MAX_BYTES}-byte limit"
(( changed <= MAX_CHANGED_FILES )) || die "${changed} changed paths exceeds the ${MAX_CHANGED_FILES}-path refresh limit"

echo "Upstream snapshot budget: OK"
