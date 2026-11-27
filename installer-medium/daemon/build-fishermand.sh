#!/usr/bin/env bash
# Build the installer daemon `fishermand` from a pinned fisherman commit
# (tunaOS#4905, ADR 0018).
#
# Usage: installer-medium/daemon/build-fishermand.sh REPO REF OUTROOT [--dry-run]
#
# Fetches REF (a full 40-hex commit of REPO, never a branch), builds the
# static Go binary cmd/fishermand of fisherman's Go module with CGO off (the
# module is at fisherman/ of tuna-os/fisherman and at fisherman/fisherman/ of
# tuna-os/installer: fisherman-module-dir.sh), and installs it as
# OUTROOT/usr/libexec/fishermand. OUTROOT is a staging tree that
# Containerfile.live copies over the live image's /usr. It also records the
# commit in OUTROOT/usr/share/medium-live/fishermand.ref and the file list in
# OUTROOT/usr/share/medium-live/payload.d/fishermand.list, which the install
# post hook reads to remove the daemon from the installed copy. With
# --dry-run, print the commands and exit 0.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REPO="${1:?usage: build-fishermand.sh REPO REF OUTROOT [--dry-run]}"
REF="${2:?usage: build-fishermand.sh REPO REF OUTROOT [--dry-run]}"
OUT="${3:?usage: build-fishermand.sh REPO REF OUTROOT [--dry-run]}"
DRY_RUN="${4:-}"

[[ "${REF}" =~ ^[0-9a-f]{40}$ ]] || {
	echo "fishermand: REF must be a full 40-hex commit, got '${REF}'" >&2
	exit 1
}
[[ "${REPO}" == https://* ]] || {
	echo "fishermand: REPO must be an https:// git URL, got '${REPO}'" >&2
	exit 1
}

BIN=/usr/libexec/fishermand
echo "fishermand: ${REPO} @ ${REF} -> ${OUT}${BIN}"
if [[ "${DRY_RUN}" = "--dry-run" ]]; then
	echo "git fetch --depth 1 ${REPO} ${REF}; cd \$(fisherman-module-dir.sh checkout); CGO_ENABLED=0 go build -trimpath -ldflags '-s -w' ./cmd/fishermand (dry run: nothing built)"
	exit 0
fi

SRC="$(mktemp -d "${TMPDIR:-/tmp}/fishermand-src.XXXXXX")"
trap 'rm -rf -- "${SRC}"' EXIT
git init -q "${SRC}"
git -C "${SRC}" fetch -q --depth 1 "${REPO}" "${REF}"
git -C "${SRC}" checkout -q FETCH_HEAD
[[ "$(git -C "${SRC}" rev-parse HEAD)" = "${REF}" ]] || {
	echo "fishermand: fetched commit does not match ${REF}" >&2
	exit 1
}

install -d "${OUT}/usr/libexec" "${OUT}/usr/share/medium-live/payload.d"
MODULE="$("${HERE}/fisherman-module-dir.sh" "${SRC}")"
(cd "${MODULE}" && CGO_ENABLED=0 go build -trimpath -ldflags '-s -w' \
	-o "${OUT}${BIN}" ./cmd/fishermand)
chmod 0755 "${OUT}${BIN}"
# A dynamic binary would break on bases with another libc: the daemon is the
# one component of the medium that must run on every cell.
if ldd "${OUT}${BIN}" >/dev/null 2>&1; then
	echo "fishermand: ${BIN} is dynamically linked; expected a static binary" >&2
	exit 1
fi
"${OUT}${BIN}" --list-scenarios >/dev/null
echo "${REF}" >"${OUT}/usr/share/medium-live/fishermand.ref"
printf '%s\n' "${BIN}" /usr/share/medium-live/fishermand.ref >"${OUT}/usr/share/medium-live/payload.d/fishermand.list"
echo "fishermand: built ${BIN} ($(wc -c <"${OUT}${BIN}") bytes, static)"
