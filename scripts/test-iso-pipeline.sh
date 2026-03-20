#!/usr/bin/env bash
# Full ISO test pipeline: ensure image → build ISO → verify boot → [install test].
#
# Usage: scripts/test-iso-pipeline.sh <variant> [flavor] [source] [install] [port]
#   variant  - e.g. yellowfin, albacore
#   flavor   - default: gnome
#   source   - local | ghcr | registry  (default: local)
#   install  - 0 | 1  run install-test step  (default: 0)
#   port     - registry port (default: 5000), only used when source=registry

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VARIANT="${1:-}"
FLAVOR="${2:-gnome}"
SOURCE="${3:-local}"
INSTALL="${4:-0}"
PORT="${5:-5000}"

if [[ -z "$VARIANT" ]]; then
	echo "Usage: test-iso-pipeline.sh <variant> [flavor] [source] [install] [port]" >&2
	exit 1
fi

PASS=0
FAIL=0

step() {
	echo ""
	echo "════════════════════════════════════════"
	echo " $*"
	echo "════════════════════════════════════════"
}

# ── Step 1: Ensure image ────────────────────────────────────────────────────

step "Step 1: Ensure image (source=${SOURCE})"

case "$SOURCE" in
local)
	if ! podman image exists "localhost/${VARIANT}:${FLAVOR}" 2>/dev/null; then
		echo "==> Image not found locally; building..."
		just build "$VARIANT" "$FLAVOR"
	else
		echo "==> Image localhost/${VARIANT}:${FLAVOR} already exists."
	fi
	;;
ghcr)
	echo "==> Pulling from ghcr.io/tuna-os/${VARIANT}:${FLAVOR}..."
	podman pull "ghcr.io/tuna-os/${VARIANT}:${FLAVOR}"
	podman tag "ghcr.io/tuna-os/${VARIANT}:${FLAVOR}" "localhost/${VARIANT}:${FLAVOR}"
	;;
registry)
	echo "==> Pulling from registry at localhost:${PORT}/${VARIANT}:${FLAVOR}..."
	podman pull --tls-verify=false "localhost:${PORT}/${VARIANT}:${FLAVOR}"
	podman tag "localhost:${PORT}/${VARIANT}:${FLAVOR}" "localhost/${VARIANT}:${FLAVOR}"
	;;
*)
	echo "ERROR: Unknown source '${SOURCE}'. Use local, ghcr, or registry." >&2
	exit 1
	;;
esac
PASS=$((PASS + 1))
echo "✓ Step 1 passed"

# ── Step 2: Build ISO ───────────────────────────────────────────────────────

step "Step 2: Build ISO"
sudo just live-iso "$VARIANT" "$FLAVOR" local
PASS=$((PASS + 1))
echo "✓ Step 2 passed"

# ── Step 3: Find ISO file ───────────────────────────────────────────────────

step "Step 3: Find ISO file"
BUILD_DIR=".build/live-iso/${VARIANT}-${FLAVOR}"
ISO_FILE=$(find "${BUILD_DIR}" -maxdepth 2 -name "*.iso" 2>/dev/null | head -1 || true)

if [[ -z "${ISO_FILE}" ]] || [[ ! -f "${ISO_FILE}" ]]; then
	echo "ERROR: No ISO found in ${BUILD_DIR}" >&2
	exit 1
fi
echo "==> Found ISO: ${ISO_FILE}"
PASS=$((PASS + 1))
echo "✓ Step 3 passed"

# ── Step 4: Verify boot ─────────────────────────────────────────────────────

step "Step 4: Verify boot"
if just verify-iso "${ISO_FILE}"; then
	PASS=$((PASS + 1))
	echo "✓ Step 4 passed"
else
	FAIL=$((FAIL + 1))
	echo "✗ Step 4 FAILED: verify-iso returned non-zero"
fi

# ── Step 5: Install test (optional) ────────────────────────────────────────

if [[ "$INSTALL" == "1" ]]; then
	step "Step 5: Install test"
	if just install-test "${ISO_FILE}" kickstart=tests/anaconda-ks.cfg; then
		PASS=$((PASS + 1))
		echo "✓ Step 5 passed"
	else
		FAIL=$((FAIL + 1))
		echo "✗ Step 5 FAILED: install-test returned non-zero"
	fi
fi

# ── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "════════════════════════════════════════"
echo " Pipeline summary for ${VARIANT}/${FLAVOR}"
echo " Source: ${SOURCE}  ISO: ${ISO_FILE}"
echo " Passed: ${PASS}  Failed: ${FAIL}"
echo "════════════════════════════════════════"

if [[ "$FAIL" -gt 0 ]]; then
	echo "ERROR: ${FAIL} step(s) failed." >&2
	exit 1
fi
echo "All steps passed."
