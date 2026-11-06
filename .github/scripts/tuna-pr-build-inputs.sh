#!/usr/bin/env bash
# Read changed paths, one per line. Default: boolean exit status (0 relevant,
# 1 unrelated). --variants: emit the selected JSON array and always exit 0.
# Keep the admitted set equal to tuna_rollout in tunaos.toml (admission test).
set -euo pipefail

mode="${1:-}"
if [[ -n "$mode" && "$mode" != --variants ]]; then
	printf 'Usage: %s [--variants]\n' "$0" >&2
	exit 2
fi
all=(marlin yellowfin albacore skipjack bonito wahoo bonito-rawhide grouper flounder flounder-sid sailfin)
declare -A selected=()
full=false

# tunaos.toml is the source of the generated manifests. Only isolated edits to
# existing admitted variants are proven local here. Everything else (including
# shared desktop/package tables, unknown sections, parse/fetch errors, and a
# missing base SHA) retains the full matrix. Canaries still see the raw path.
config_variants() {
	python3 - "${BASH_SOURCE[0]}" <<'PY'
import os
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve().parents[2]
sys.path.insert(0, str(root / "scripts"))
from lib.tunaos_config import parse
try:
    base = os.environ["TUNA_PR_BASE_SHA"]
    if len(base) != 40 or any(c not in "0123456789abcdef" for c in base):
        raise ValueError("not a commit SHA")
    old = parse(subprocess.check_output(
        ["git", "show", f"{base}:tunaos.toml"], cwd=root, text=True,
        stderr=subprocess.DEVNULL,
    ))
    new = parse((root / "tunaos.toml").read_text())
    # Unknown/new/deleted variants and rollout changes must not narrow coverage.
    before, after = old.pop("variants"), new.pop("variants")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("unknown variant config")
    if old != new or before.keys() != after.keys():
        raise ValueError("shared config changed")
    def same_shape(left, right):
        if isinstance(left, dict) and isinstance(right, dict):
            return left.keys() == right.keys() and all(
                same_shape(left[key], right[key]) for key in left
            )
        if isinstance(left, list) and isinstance(right, list):
            return len(left) == len(right) and all(
                same_shape(a, b) for a, b in zip(left, right)
            )
        return type(left) is type(right)
    if not same_shape(before, after):
        raise ValueError("unknown or changed variant config structure")
    changed = [v for v in before if before[v] != after[v]]
    if not changed:
        raise ValueError("no proven variant-only change")
    print(" ".join(changed))
except (KeyError, ValueError, OSError, subprocess.SubprocessError):
    print("all")
PY
}

while IFS= read -r path || [[ -n "$path" ]]; do
	affected=()
	case "$path" in
	# resolve-flavor.sh routes these recipes; install-desktop.sh selects the
	# Debian/Arch manifest before the shared one. Shared recipes stay full.
	Containerfile.arch | manifests/desktops/tuna-arch.yaml)
		affected=(marlin)
		;;
	Containerfile.debian | manifests/desktops/tuna-debian.yaml)
		affected=(flounder flounder-sid)
		;;
	Containerfile.ubuntu)
		affected=(grouper)
		;;
	Containerfile.opensuse)
		affected=(sailfin)
		;;
	tunaos.toml)
		if scoped="$(config_variants)" && [[ -n "$scoped" ]]; then
			read -r -a affected <<<"$scoped"
		else
			full=true
		fi
		;;
	system_files_overrides/bonito/*)
		affected=(bonito bonito-rawhide)
		;;
	system_files_overrides/flounder/*)
		affected=(flounder flounder-sid)
		;;
	system_files_overrides/* | manifests/desktop-contracts/*)
		# copy_systemfiles_for and the contract installer address variant
		# directories by exact ID. Unknown/shared directory names fail open.
		remainder="${path#system_files_overrides/}"
		remainder="${remainder#manifests/desktop-contracts/}"
		affected=("${remainder%%/*}")
		;;
	.github/build-config.yml | .github/workflows/tuna-pr-images.yml | .github/workflows/build-variant.yml | .github/workflows/reusable-build-image.yml | .github/actions/* | .github/scripts/* | Containerfile* | build_scripts/* | experiences/* | image-versions.yaml | registry-map.yaml | manifests/* | config/* | system_files/* | files/* | scripts/* | Justfile | just/* | tests/functional/*)
		full=true
		;;
	*)
		continue
		;;
	esac
	for variant in "${affected[@]}"; do
		known=false
		for admitted in "${all[@]}"; do
			if [[ "$variant" == "$admitted" ]]; then
				selected["$variant"]=1
				known=true
				break
			fi
		done
		[[ "$known" == true ]] || full=true
	done
	# Do not exit early: multiple variant-local paths select their union, and
	# any shared/unknown input restores all cells regardless of path order.
done

variants=()
for variant in "${all[@]}"; do
	if [[ "$full" == true || -v "selected[$variant]" ]]; then
		variants+=("$variant")
	fi
done
if [[ "$mode" == --variants ]]; then
	printf '['
	separator=''
	for variant in "${variants[@]}"; do
		printf '%s"%s"' "$separator" "$variant"
		separator=,
	done
	printf ']\n'
elif ((${#variants[@]} > 0)); then
	printf 'Tuna image inputs changed: %s\n' "${variants[*]}"
else
	exit 1
fi
