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
all=(marlin yellowfin albacore skipjack bonito wahoo bonito-rawhide grouper guppy flounder flounder-sid sailfin)
declare -A selected=()
full=false

# tunaos.toml is the source of the generated manifests. Only isolated edits to
# existing admitted variants are proven local here, and an edit to [iso_delivery]
# alone consumes no pull-request build at all. Everything else (including shared
# desktop/package tables, unknown sections, parse/fetch errors, and a missing
# base SHA) retains the full matrix. Canaries still see the raw path unless the
# same helper proves the edit ISO-only (canary-cell-inputs.sh).
config_variants() {
	python3 "$(dirname "${BASH_SOURCE[0]}")/tunaos-config-scope.py"
}

# image-versions.yaml is mostly Renovate digest bumps. utah-packages, brew and
# gnome50-el10-packages are consumed only as `FROM` stages of Containerfile.el10
# (build-image-inner.sh passes the refs to every build; the other Containerfiles
# declare none of them), so a bump of only those digests can change only the
# variants resolve-flavor.sh sends to that recipe. tests/test_pr_canary_cells.py
# pins this list to resolve-flavor.sh. The fisherman-golang image and the
# downloads.fisherman / bootc_installer pins are read only by luks-e2e.yml and
# the live ISO fetch (nothing under Containerfile*, build_scripts/ or the build
# recipe reads them), so a bump of only those selects no cell. Anything else in
# the file, any comment or non-digest edit, or a missing base SHA keeps the full
# matrix.
el10_variants=(yellowfin albacore skipjack bonito bonito-rawhide wahoo)
image_versions_variants() {
	python3 - "${BASH_SOURCE[0]}" "${el10_variants[*]}" <<'PY'
import os
from pathlib import Path
import re
import subprocess
import sys

EL10_ONLY = {"utah-packages", "brew", "gnome50-el10-packages"}
# Pins no image build reads: luks-e2e.yml (fisherman, its Go builder) and
# live-iso/common/src/fetch-installer-bundle.sh (bootc_installer).
NON_IMAGE = {"fisherman-golang", "downloads.fisherman", "downloads.bootc_installer",
             "downloads.bootc_installer_sha256"}

def digests(text):
    """Return ({pin name: value}, text with every such value blanked)."""
    names, rest, section, name, in_installer_sums = {}, [], None, None, False
    for line in text.splitlines():
        if re.match(r"^[A-Za-z_]+:", line):
            section = line.split(":")[0]
            in_installer_sums = False
        found = re.match(r"^  - name:\s*(\S+)\s*$", line)
        if section == "images" and found:
            name = found[1]
        found = re.match(r"^(    digest:\s*)(sha256:[0-9a-f]{64})\s*$", line)
        if section == "images" and found and name:
            names[name] = found[2]
            line = found[1] + "<digest>"
        found = re.match(r"^(  (?:fisherman|bootc_installer):\s*)(\"[^\"]+\")\s*$", line)
        if section == "downloads" and found:
            names["downloads." + line.split(":")[0].strip()] = found[2]
            line = found[1] + "<pin>"
        if section == "downloads":
            if re.match(r"^  bootc_installer_sha256:\s*$", line):
                in_installer_sums = True
                names.setdefault("downloads.bootc_installer_sha256", "")
            elif in_installer_sums:
                found = re.match(r"^(    (?:x86_64|aarch64):\s*)(\"[0-9a-f]{64}\")\s*$", line)
                if found:
                    names["downloads.bootc_installer_sha256"] += found[2]
                    line = found[1] + "<pin>"
                else:
                    in_installer_sums = False
        rest.append(line)
    return names, "\n".join(rest)

try:
    base = os.environ["TUNA_PR_BASE_SHA"]
    if len(base) != 40 or any(c not in "0123456789abcdef" for c in base):
        raise ValueError("not a commit SHA")
    root = Path(sys.argv[1]).resolve().parents[2]
    old = subprocess.check_output(
        ["git", "show", f"{base}:image-versions.yaml"], cwd=root, text=True,
        stderr=subprocess.DEVNULL,
    )
    new = (root / "image-versions.yaml").read_text(encoding="utf-8")
    before, before_rest = digests(old)
    after, after_rest = digests(new)
    if before_rest != after_rest or before.keys() != after.keys():
        raise ValueError("more than image digests changed")
    changed = {name for name in before if before[name] != after[name]}
    if not changed or not changed <= EL10_ONLY | NON_IMAGE:
        raise ValueError("a digest outside the el10-only stages changed")
    print(sys.argv[2] if changed & EL10_ONLY else "none")
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
		if scoped="$(config_variants)" && [[ -n "$scoped" && "$scoped" != all ]]; then
			# config_variants proved each name is an existing variant whose own
			# table changed. One outside the admitted set (hummingbird, gurnard,
			# guppy, ...) builds no Tuna cell, so its edit selects nothing:
			# 7 full-matrix runs (1,836 job-min) in one week came from
			# hummingbird-only base-image digest bumps.
			for changed in $scoped; do
				for admitted in "${all[@]}"; do
					[[ "$changed" == "$admitted" ]] && affected+=("$changed")
				done
			done
		else
			full=true
		fi
		;;
	image-versions.yaml)
		if scoped="$(image_versions_variants)" && [[ -n "$scoped" && "$scoped" != all ]]; then
			[[ "$scoped" == none ]] || read -r -a affected <<<"$scoped"
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
	# Scripts and actions the PR image path does not run. Everything not listed
	# stays a full-matrix input. tests/test_pr_canary_cells.py checks that no
	# build entry point (Containerfiles, build_scripts/, the build recipe, the
	# two reusable jobs, the local actions) names a path listed here.
	scripts/installer-walkthrough.py | scripts/run-walkthrough.sh | scripts/install-checkpoints.py | scripts/iso_*.py | scripts/collect-qualification-receipt.py | scripts/summarize-strict-legs.py | scripts/strict-journal-extract.py | scripts/live-overlay-matrix.sh | scripts/dispatch-live-overlay.sh | scripts/fork-simulation.py | scripts/fork-simulation-gh | scripts/run-fork-simulation.sh | scripts/ci-cleanup.py | scripts/ci-reap-stale.py | scripts/lib/ci-scope.sh | scripts/check-installer-fisherman-pins.py)
		continue
		;;
	# .github/actions/ and .github/scripts/: only what the build path calls
	# (ghcr-login, prepare-config, setup-yq, install-oras.sh) or what selects
	# cells (the two detectors and the config-scope helper).
	.github/actions/ghcr-login/* | .github/actions/prepare-config/* | .github/actions/setup-yq/* | .github/scripts/install-oras.sh | .github/scripts/tuna-pr-build-inputs.sh | .github/scripts/canary-cell-inputs.sh | .github/scripts/tunaos-config-scope.py)
		full=true
		;;
	.github/actions/* | .github/scripts/*)
		continue
		;;
	.github/build-config.yml | .github/workflows/tuna-pr-images.yml | .github/workflows/build-variant.yml | .github/workflows/reusable-build-image.yml | Containerfile* | build_scripts/* | experiences/* | registry-map.yaml | manifests/* | config/* | system_files/* | files/* | scripts/* | Justfile | just/* | tests/functional/*)
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
