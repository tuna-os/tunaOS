#!/usr/bin/env bash
# scripts/install-corral.sh — build the pinned corral into a directory.
#
# Usage: scripts/install-corral.sh <bin-dir>
#
# The pin is `downloads.corral` in image-versions.yaml, a tuna-os/corral
# commit. corral publishes no release binaries, so this builds it with
# `go install`; Go's toolchain switching fetches the Go version corral's go.mod
# asks for when the runner's is older.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${1:?usage: $0 <bin-dir>}"

ref=$(sed -nE 's/^[[:space:]]*corral:[[:space:]]*"?([^"[:space:]]+)"?[[:space:]]*$/\1/p' \
	"${REPO_ROOT}/image-versions.yaml" | head -n 1)
if [[ ! "$ref" =~ ^[0-9a-f]{40}$ ]]; then
	echo "ERROR: downloads.corral in image-versions.yaml is not a 40-character commit: '${ref}'" >&2
	exit 1
fi
command -v go >/dev/null || {
	echo "ERROR: go is not on PATH; corral is built from source (CI: actions/setup-go first)" >&2
	exit 1
}

mkdir -p "$BIN_DIR"
GOBIN="$(cd "$BIN_DIR" && pwd)" GOTOOLCHAIN=auto go install "github.com/tuna-os/corral@${ref}"
echo "==> corral ${ref} installed to ${BIN_DIR}/corral"
