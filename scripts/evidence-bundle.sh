#!/usr/bin/env bash
# Build one normalized evidence bundle from a gate's existing output directory.
# Usage: evidence-bundle.sh <variant:flavor> <criterion[,criterion...]> <run-dir>
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <variant:flavor> <criterion[,criterion...]> <run-dir>" >&2
  exit 2
fi

cell=$1
criteria=$2
run_dir=$3
if [[ ! "$cell" =~ ^[a-z0-9-]+:[a-z0-9-]+$ ]]; then
  echo "invalid cell '$cell' (expected variant:flavor)" >&2
  exit 2
fi
if [[ ! "$criteria" =~ ^[a-z0-9_-]+(,[a-z0-9_-]+)*$ ]]; then
  echo "invalid criterion list '$criteria'" >&2
  exit 2
fi
if [[ ! -d "$run_dir" ]]; then
  echo "run directory does not exist: $run_dir" >&2
  exit 2
fi
command -v jq >/dev/null || {
  echo "jq is required" >&2
  exit 2
}

variant=${cell%%:*}
flavor=${cell#*:}
arch=${EVIDENCE_ARCH:-}
if [[ -z "$arch" ]]; then
  case "$(uname -m)" in
  x86_64) arch=amd64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) arch=$(uname -m) ;;
  esac
fi
if [[ ! "$arch" =~ ^[a-zA-Z0-9_.-]+$ ]]; then
  echo "invalid evidence architecture '$arch'" >&2
  exit 2
fi

root=${EVIDENCE_ROOT:-evidence}
out="${root}/${variant}/${flavor}/${arch}"
mkdir -p "$out"

status=${EVIDENCE_STATUS:-unknown}
if [[ -f "$run_dir/result.json" ]]; then
  status=$(jq -r '.status // "unknown"' "$run_dir/result.json")
fi

jq -n \
  --arg cell "$cell" --arg variant "$variant" --arg flavor "$flavor" \
  --arg arch "$arch" --arg criteria "$criteria" --arg status "$status" \
  --arg run_id "${GITHUB_RUN_ID:-}" --arg run_attempt "${GITHUB_RUN_ATTEMPT:-}" \
  --arg repository "${GITHUB_REPOSITORY:-}" --arg sha "${GITHUB_SHA:-}" \
  --arg timestamp "$(date -u +%FT%TZ)" \
  '{schema_version:1, cell:$cell, variant:$variant, flavor:$flavor,
	  architecture:$arch, criteria:($criteria|split(",")), status:$status,
	  run:{id:$run_id, attempt:$run_attempt, repository:$repository},
	  git_sha:$sha, timestamp:$timestamp}' >"$out/metadata.json"

copy_if_present() {
  local source=$1 destination=$2
  if [[ -f "$run_dir/$source" ]]; then
    cp "$run_dir/$source" "$out/$destination"
  fi
}

# Preserve common machine-readable inputs under their schema names.
for file in image.json packages.txt omissions.json desktop-contract.json \
  lifecycle.json sbom.spdx.json provenance.json signature.json; do
  copy_if_present "$file" "$file"
done

# Normalize the ad-hoc names emitted by the existing boot/install gates.
copy_if_present serial.log boot.log
copy_if_present installed-serial.log boot-journal.txt
copy_if_present luks-evidence.log installer.log
copy_if_present result.json result.json

if [[ -f "$run_dir/result.json" ]]; then
  jq '{cell,variant,desktop,status,reason,exit}' "$run_dir/result.json" \
    >"$out/desktop-contract.json"
  jq '{cell,status:.omissions_status,reason:.omissions_reason}' \
    "$run_dir/result.json" >"$out/omissions.json"
fi
if [[ "$criteria" == *install* ]]; then
  jq -n --arg status "$status" \
    --arg log "$([[ -f "$out/installer.log" ]] && echo installer.log || true)" \
    '{status:$status, installer_log:$log}' >"$out/install-result.json"
fi

# Screenshots and other diagnostic logs retain their names; consumers can use
# metadata.json to identify the cell without encoding identity into filenames.
find "$run_dir" -maxdepth 1 -type f \( -name '*.png' -o -name '*.webm' \) \
  -exec cp -t "$out" {} + 2>/dev/null || true

printf '%s\n' "$out"
