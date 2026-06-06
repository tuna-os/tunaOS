#!/usr/bin/env bash
# sync-upstream-snapshots.sh — Synchronize or verify _upstream-snapshots/
#
# Usage:
#   sync-upstream-snapshots.sh           Sync all upstreams
#   sync-upstream-snapshots.sh --check   Verify snapshots match upstream SHA (CI mode)
#   sync-upstream-snapshots.sh <name>    Sync a single upstream (e.g. "aurora")
#
# If _upstream-snapshots/<name>/.sync-manifest.yaml exists, its include list
# replaces the paths from .snapshot.json, allowing minimized vendoring.
#
# Exit codes:
#   0 — in sync (check mode) or sync successful
#   1 — drift detected (check mode) or sync failed
#   2 — usage error

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SNAPSHOTS_DIR="${REPO_ROOT}/_upstream-snapshots"

CHECK_MODE=0
TARGET="all"

# ── Argument parsing ──
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check|-c)
            CHECK_MODE=1
            shift
            ;;
        *)
            TARGET="$1"
            shift
            ;;
    esac
done

# ── Dependency check ──
for cmd in git jq; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: '$cmd' is required but not installed." >&2
        exit 2
    fi
done

# ── Color helpers ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Read sync-manifest.yaml include paths if present ──
read_manifest_paths() {
    local snap_dir="$1"
    local manifest="${snap_dir}/.sync-manifest.yaml"

    if [[ -f "${manifest}" ]]; then
        # Extract include paths, join with ':'
        "${YQ:-yq}" -r '.include | join(":")' "${manifest}" 2>/dev/null || echo ""
    else
        echo ""
    fi
}

# ── Sync a single upstream ──
sync_upstream() {
    local name="$1"
    local snap_dir="${SNAPSHOTS_DIR}/${name}"
    local meta_file="${snap_dir}/.snapshot.json"

    if [[ ! -f "${meta_file}" ]]; then
        echo "ERROR: ${meta_file} not found" >&2
        return 1
    fi

    local upstream branch sha paths
    upstream=$(jq -r '.upstream' "${meta_file}")
    branch=$(jq -r '.branch' "${meta_file}")
    sha=$(jq -r '.sha' "${meta_file}")

    # Prefer .sync-manifest.yaml include paths, fall back to .snapshot.json paths
    local manifest_paths
    manifest_paths=$(read_manifest_paths "${snap_dir}")
    if [[ -n "${manifest_paths}" ]]; then
        paths="${manifest_paths}"
        echo "  Using manifest: .sync-manifest.yaml"
    else
        paths=$(jq -r '.paths' "${meta_file}")
    fi

    if [[ -z "${upstream}" || -z "${branch}" || -z "${sha}" ]]; then
        echo "ERROR: ${meta_file} is missing required fields (upstream, branch, sha)" >&2
        return 1
    fi

    local tmpdir
    tmpdir=$(mktemp -d)
    trap "rm -rf '${tmpdir}'" RETURN

    echo "  Upstream: ${upstream} @ ${sha:0:8} (${branch})"
    echo "  Paths: ${paths}"

    # Shallow clone at pinned SHA
    if ! git clone --quiet --depth=1 --branch="${sha}" "${upstream}" "${tmpdir}/upstream" 2>/dev/null; then
        # Fallback: full clone then checkout SHA
        echo "  (shallow clone failed, trying fetch at SHA...)"
        if ! git clone --quiet --no-checkout "${upstream}" "${tmpdir}/upstream" 2>/dev/null; then
            echo "ERROR: Failed to clone ${upstream}" >&2
            return 1
        fi
        git -C "${tmpdir}/upstream" fetch --quiet --depth=1 origin "${sha}" 2>/dev/null || true
        git -C "${tmpdir}/upstream" checkout --quiet "${sha}" 2>/dev/null || {
            echo "ERROR: Failed to checkout ${sha:0:8} from ${upstream}" >&2
            return 1
        }
    fi

    # Validate that checked-out commit matches pinned SHA
    local actual_sha
    actual_sha=$(git -C "${tmpdir}/upstream" rev-parse HEAD)
    if [[ "${actual_sha}" != "${sha}" ]]; then
        echo "ERROR: Checked out ${actual_sha:0:8}, expected ${sha:0:8}" >&2
        return 1
    fi

    if [[ "${CHECK_MODE}" == "1" ]]; then
        # ── Check mode: compare files ──
        local drift=0
        IFS=':' read -ra PATH_LIST <<< "${paths}"
        for p in "${PATH_LIST[@]}"; do
            if [[ ! -e "${tmpdir}/upstream/${p}" ]]; then
                echo "  ${YELLOW}WARN:${NC} upstream path '${p}' no longer exists at ${sha:0:8}"
                continue
            fi

            if [[ ! -e "${snap_dir}/${p}" ]]; then
                echo "  ${RED}DRIFT:${NC} '${p}' exists upstream but not in snapshot"
                drift=1
                continue
            fi

            # Compare directories recursively, files directly
            if ! diff -rq "${tmpdir}/upstream/${p}" "${snap_dir}/${p}" &>/dev/null; then
                local diff_output
                diff_output=$(diff -rq "${tmpdir}/upstream/${p}" "${snap_dir}/${p}" 2>/dev/null || true)
                echo "  ${RED}DRIFT:${NC} '${p}' differs from upstream"
                echo "    ${diff_output}" | head -10
                drift=1
            fi
        done

        if [[ "${drift}" == "1" ]]; then
            echo "  ${RED}FAIL:${NC} ${name} snapshot is out of sync with upstream"
            return 1
        else
            echo "  ${GREEN}OK:${NC} ${name} snapshot matches upstream @ ${sha:0:8}"
            return 0
        fi
    else
        # ── Sync mode: copy files ──
        IFS=':' read -ra PATH_LIST <<< "${paths}"
        for p in "${PATH_LIST[@]}"; do
            if [[ ! -e "${tmpdir}/upstream/${p}" ]]; then
                echo "  ${YELLOW}SKIP:${NC} upstream path '${p}' no longer exists"
                continue
            fi

            # Remove old snapshot, copy from upstream
            rm -rf "${snap_dir:?}/${p}"
            cp -r "${tmpdir}/upstream/${p}" "${snap_dir}/${p}"
            echo "  Synced: ${p}"
        done

        # Update synced_at timestamp
        local now
        now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        local tmp_json
        tmp_json=$(mktemp)
        jq --arg ts "${now}" '.synced_at = $ts' "${meta_file}" > "${tmp_json}"
        mv "${tmp_json}" "${meta_file}"

        echo "  ${GREEN}OK:${NC} ${name} synced from ${sha:0:8}"
        return 0
    fi
}

# ── Main ──
echo "==> Upstream snapshot sync"
echo "    Mode: $([[ "${CHECK_MODE}" == "1" ]] && echo "CHECK" || echo "SYNC")"
echo "    Target: ${TARGET}"
echo ""

if [[ "${TARGET}" == "all" ]]; then
    # Process all upstreams found in _upstream-snapshots/
    local errors=0
    for snap_dir in "${SNAPSHOTS_DIR}"/*/; do
        [[ -d "${snap_dir}" ]] || continue
        local name
        name=$(basename "${snap_dir}")
        [[ "${name}" == "." || "${name}" == ".." ]] && continue
        [[ ! -f "${snap_dir}.snapshot.json" ]] && continue

        echo "--- ${name} ---"
        if ! sync_upstream "${name}"; then
            errors=$(( errors + 1 ))
        fi
        echo ""
    done

    if [[ "${errors}" -gt 0 ]]; then
        if [[ "${CHECK_MODE}" == "1" ]]; then
            echo "==> ${RED}FAIL:${NC} ${errors} upstream(s) out of sync"
        else
            echo "==> ${RED}FAIL:${NC} ${errors} upstream(s) failed to sync"
        fi
        exit 1
    fi
else
    if ! sync_upstream "${TARGET}"; then
        exit 1
    fi
fi

if [[ "${CHECK_MODE}" == "1" ]]; then
    echo "==> ${GREEN}PASS:${NC} All snapshots in sync with upstream"
else
    echo "==> ${GREEN}Done:${NC} Upstream snapshots synchronized"
fi
