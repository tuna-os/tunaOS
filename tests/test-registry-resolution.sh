#!/usr/bin/env bash
# test-registry-resolution.sh — Validate registry_ref() resolution.
#
# Tests that registry_ref() produces correct image references from
# registry-map.yaml defaults, and that env var overrides apply correctly.
#
# Run:
#   bash tests/test-registry-resolution.sh
#
# CI integration: called from CI workflow job that sources _registry.sh.
set -euo pipefail

PASS=0
FAIL=0

check() {
	local desc="$1"
	local expected="$2"
	local actual="$3"
	if [[ "${actual}" == "${expected}" ]]; then
		echo "  PASS: ${desc}"
		PASS=$((PASS + 1))
	else
		echo "  FAIL: ${desc}"
		echo "    expected: ${expected}"
		echo "    actual:   ${actual}"
		FAIL=$((FAIL + 1))
	fi
}

echo "=== Registry Resolution Tests ==="
echo ""

# Load registry helper (repo root is 2 levels up from tests/)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${REPO_ROOT}/scripts/_registry.sh"

# --- Default resolution (no overrides) ---
echo "[Default resolution]"

check "common default" \
	"ghcr.io/projectbluefin/common:latest" \
	"$(registry_ref common)"

check "brew default" \
	"ghcr.io/ublue-os/brew:latest" \
	"$(registry_ref brew)"

check "almalinux-bootc default" \
	"quay.io/almalinuxorg/almalinux-bootc:10" \
	"$(registry_ref almalinux-bootc)"

check "centos-bootc default" \
	"quay.io/centos-bootc/centos-bootc:stream10" \
	"$(registry_ref centos-bootc)"

check "fedora-bootc default" \
	"quay.io/fedora/fedora-bootc:44" \
	"$(registry_ref fedora-bootc)"

check "coreos-chunkah default" \
	"quay.io/coreos/chunkah:latest" \
	"$(registry_ref coreos-chunkah)"

check "novnc default" \
	"ghcr.io/novnc/novnc:latest" \
	"$(registry_ref novnc)"

check "qemu default" \
	"ghcr.io/qemus/qemu:latest" \
	"$(registry_ref qemu)"

check "bluefin-iso default" \
	"ghcr.io/hanthor/bluefin:lts" \
	"$(registry_ref bluefin-iso)"

check "akmods default (no tag)" \
	"ghcr.io/ublue-os" \
	"$(registry_ref akmods)"

check "akmods-nvidia-open default" \
	"ghcr.io/ublue-os/akmods-nvidia-open" \
	"$(registry_ref akmods-nvidia-open)"

check "almalinux-bootc-kitten default" \
	"quay.io/almalinuxorg/almalinux-bootc:10-kitten" \
	"$(registry_ref almalinux-bootc-kitten)"

# --- Explicit tag/digest override via argument ---
echo ""
echo "[Explicit tag/digest argument]"

check "common with explicit tag" \
	"ghcr.io/projectbluefin/common:v99" \
	"$(registry_ref common ':v99')"

check "common with digest" \
	"ghcr.io/projectbluefin/common@sha256:abc123" \
	"$(registry_ref common '@sha256:abc123')"

check "akmods with explicit tag" \
	"ghcr.io/ublue-os:v2" \
	"$(registry_ref akmods ':v2')"

# --- Registry override ---
echo ""
echo "[Registry override: TUNA_REGISTRY_ghcr=mirror.example.com]"

TUNA_REGISTRY_ghcr=mirror.example.com
check "common with ghcr override" \
	"mirror.example.com/projectbluefin/common:latest" \
	"$(registry_ref common)"

check "brew with ghcr override" \
	"mirror.example.com/ublue-os/brew:latest" \
	"$(registry_ref brew)"

check "novnc with ghcr override" \
	"mirror.example.com/novnc/novnc:latest" \
	"$(registry_ref novnc)"

# quay.io should NOT be affected
check "almalinux-bootc still quay" \
	"quay.io/almalinuxorg/almalinux-bootc:10" \
	"$(registry_ref almalinux-bootc)"

unset TUNA_REGISTRY_ghcr

# --- Quay override ---
echo ""
echo "[Registry override: TUNA_REGISTRY_quay=quay-mirror.internal]"

TUNA_REGISTRY_quay=quay-mirror.internal
check "almalinux-bootc with quay override" \
	"quay-mirror.internal/almalinuxorg/almalinux-bootc:10" \
	"$(registry_ref almalinux-bootc)"

check "centos-bootc with quay override" \
	"quay-mirror.internal/centos-bootc/centos-bootc:stream10" \
	"$(registry_ref centos-bootc)"

check "ghcr image unaffected by quay override" \
	"ghcr.io/projectbluefin/common:latest" \
	"$(registry_ref common)"

unset TUNA_REGISTRY_quay

# --- Image path override ---
echo ""
echo "[Image path override: TUNA_IMAGE_PATH_common=myorg/fork]"

TUNA_IMAGE_PATH_common=myorg/fork
check "common with path override" \
	"ghcr.io/myorg/fork:latest" \
	"$(registry_ref common)"

check "brew unaffected by common path override" \
	"ghcr.io/ublue-os/brew:latest" \
	"$(registry_ref brew)"

unset TUNA_IMAGE_PATH_common

# --- Image tag override ---
echo ""
echo "[Image tag override: TUNA_IMAGE_TAG_common=gts-2026]"

TUNA_IMAGE_TAG_common=gts-2026
check "common with tag override" \
	"ghcr.io/projectbluefin/common:gts-2026" \
	"$(registry_ref common)"

check "brew unaffected by common tag override" \
	"ghcr.io/ublue-os/brew:latest" \
	"$(registry_ref brew)"

unset TUNA_IMAGE_TAG_common

# --- Combined overrides ---
echo ""
echo "[Combined: registry + path + tag overrides]"

TUNA_REGISTRY_ghcr=local:5000
TUNA_IMAGE_PATH_common=custom/common
TUNA_IMAGE_TAG_common=v5
check "common with all overrides" \
	"local:5000/custom/common:v5" \
	"$(registry_ref common)"

unset TUNA_REGISTRY_ghcr
unset TUNA_IMAGE_PATH_common
unset TUNA_IMAGE_TAG_common

# --- Hyphenated name overrides (sanitized: - → _) ---
echo ""
echo "[Hyphenated name: TUNA_IMAGE_TAG_almalinux_bootc=11]"

TUNA_IMAGE_TAG_almalinux_bootc=11
check "almalinux-bootc with sanitized tag override" \
	"quay.io/almalinuxorg/almalinux-bootc:11" \
	"$(registry_ref almalinux-bootc)"
unset TUNA_IMAGE_TAG_almalinux_bootc

echo "[Hyphenated name: TUNA_IMAGE_PATH_centos_bootc=custom/centos]"
TUNA_IMAGE_PATH_centos_bootc=custom/centos
check "centos-bootc with sanitized path override" \
	"quay.io/custom/centos:stream10" \
	"$(registry_ref centos-bootc)"
unset TUNA_IMAGE_PATH_centos_bootc

# --- Exported vars ---
echo ""
echo "[Exported environment variables]"

check "COMMON_IMAGE exported" \
	"ghcr.io/projectbluefin/common:latest" \
	"${COMMON_IMAGE:-}"

check "BREW_IMAGE exported" \
	"ghcr.io/ublue-os/brew:latest" \
	"${BREW_IMAGE:-}"

check "BASE_IMAGE exported" \
	"quay.io/almalinuxorg/almalinux-bootc:10" \
	"${BASE_IMAGE:-}"

# --- Summary ---
echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="

if [[ "${FAIL}" -gt 0 ]]; then
	exit 1
fi
