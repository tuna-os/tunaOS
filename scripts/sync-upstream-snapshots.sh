#!/usr/bin/env bash
# scripts/sync-upstream-snapshots.sh
#
# Mirror the relevant subset of each upstream sibling repo (Aurora,
# Bluefin-LTS, Zirconium) into `_upstream-snapshots/<name>/` in this
# tree. The git history of that directory becomes the content-level
# diff over time — chore/CI/docs commits with no payload changes
# collapse to no-op, and the only commits that ever land are ones
# where something we actually care about changed.
#
# This replaces the previous "Watch <Upstream>" workflows that walked
# per-commit and burned Gemini API calls deciding nothing was worth
# porting. The new model:
#
#   1. This script runs (weekly via workflow, ad-hoc by humans).
#   2. It refreshes `_upstream-snapshots/<name>/` from the upstream's
#      default branch, restricted to paths that map to anything we
#      build (build_files, system_files, Containerfile*, etc.).
#   3. Whatever changes appear in `git status -s _upstream-snapshots/`
#      is the actual content delta a reviewer needs to consider for
#      porting. Run `git diff _upstream-snapshots/` to see it.
#   4. The companion CI workflow opens a PR if the snapshot moved.
#
# Usage:
#   ./scripts/sync-upstream-snapshots.sh            # sync all configured upstreams
#   ./scripts/sync-upstream-snapshots.sh aurora     # sync just one
#
# Idempotent. Network-bound but cheap (shallow clone + rsync).

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SNAPSHOT_DIR="${REPO_ROOT}/_upstream-snapshots"
mkdir -p "${SNAPSHOT_DIR}"

# ── Upstream registry ───────────────────────────────────────────────────────
# Each entry: <slug>|<github-url>|<branch>|<colon-separated-paths>
#
# Paths are relative to the upstream's repo root. Only these get mirrored
# into `_upstream-snapshots/<slug>/`. Keep this list tight — every path
# you include here will surface diffs on every upstream chore commit that
# happens to touch it, which is exactly the noise we just got rid of.
#
# The paths chosen mirror what tunaos consumes from each upstream:
#   - build scripts (where package lists / service configs live)
#   - system_files (config that lands in the image)
#   - Containerfile / Justfile (top-level orchestration)
#   - image-versions / image-versions.yml (pinned bases)
UPSTREAMS=(
	"aurora|https://github.com/ublue-os/aurora.git|main|build_files:system_files:Containerfile.in:Justfile:image-versions.yml"
	"bluefin-lts|https://github.com/ublue-os/bluefin-lts.git|main|build_scripts:system_files:Containerfile:Containerfile.dx:Justfile:image-versions.yml"
	"zirconium|https://github.com/zirconium-dev/zirconium.git|main|mkosi.extra:mkosi.conf.d:mkosi.profiles:mkosi.conf:mkosi.bump:mkosi.postinst.chroot:mkosi.prepare.chroot:Justfile:iso.toml:iso-nvidia.toml:repos"
)

# ── Argument parsing ────────────────────────────────────────────────────────

FILTER="${1:-all}"

# ── Helpers ─────────────────────────────────────────────────────────────────

# Resolve the upstream's default branch HEAD SHA without a full clone.
upstream_head() {
	local url="$1" branch="$2"
	git ls-remote "$url" "refs/heads/${branch}" | awk '{print $1}'
}

# Shallow-fetch the upstream tree at HEAD into a temp dir.
fetch_upstream() {
	local url="$1" branch="$2" dst="$3"
	rm -rf "$dst"
	git clone --quiet --depth 1 --branch "$branch" "$url" "$dst"
	# Strip the upstream's .git so it doesn't conflict with rsync / pollute
	# our tree with a nested git repo.
	rm -rf "${dst}/.git"
}

# Filter `src` down to `paths` (colon-separated, relative paths) and
# rsync the survivors into `dst`. Anything in `dst` that no longer
# exists upstream is removed — `--delete` keeps the snapshot honest.
filter_and_copy() {
	local src="$1" dst="$2" paths="$3"
	mkdir -p "$dst"

	# Compose rsync's include/exclude rules so only the configured paths
	# (plus their parent directories) make it through. The trailing
	# /*** wildcard is rsync's idiom for "include this dir and all its
	# contents recursively".
	local rules_file
	rules_file=$(mktemp)
	# shellcheck disable=SC2064  # capture rules_file now, not at trap-time
	trap "rm -f '${rules_file}'" RETURN

	{
		# Include every parent directory of each kept path so rsync can
		# descend into them.
		IFS=':' read -ra parts <<<"$paths"
		for p in "${parts[@]}"; do
			local segs=""
			IFS='/' read -ra dirs <<<"$p"
			for d in "${dirs[@]}"; do
				if [[ -n "$segs" ]]; then
					segs="${segs}/${d}"
				else
					segs="$d"
				fi
				echo "+ /${segs}"
			done
			# Recurse into the leaf (works for both files and directories).
			echo "+ /${p}/***"
		done
		echo "- *"
	} >"$rules_file"

	rsync -a --delete --filter=". ${rules_file}" "${src}/" "${dst}/"
}

# Print a one-line summary of what the snapshot move is (for the
# wrapping workflow's PR body / commit message).
diff_summary() {
	local slug="$1"
	local rel="_upstream-snapshots/${slug}"
	if git diff --quiet -- "$rel" 2>/dev/null && [[ -z "$(git status -s -- "$rel")" ]]; then
		echo "  ${slug}: no change"
		return
	fi
	local added removed modified
	added=$(git status -s -- "$rel" | grep -c '^??' || true)
	# Count modified+deleted via git diff, which excludes untracked files
	modified=$(git diff --numstat -- "$rel" | wc -l || true)
	removed=$(git diff --diff-filter=D --name-only -- "$rel" | wc -l || true)
	echo "  ${slug}: +${added} new, ~${modified} modified, -${removed} deleted"
}

# ── Main ────────────────────────────────────────────────────────────────────

WORK=$(mktemp -d)
# shellcheck disable=SC2064  # capture WORK path now
trap "rm -rf '${WORK}'" EXIT

echo "==> Sync upstream snapshots → ${SNAPSHOT_DIR}"

for entry in "${UPSTREAMS[@]}"; do
	IFS='|' read -r slug url branch paths <<<"$entry"
	if [[ "$FILTER" != "all" ]] && [[ "$FILTER" != "$slug" ]]; then
		continue
	fi
	echo
	echo "── ${slug} (${url} @ ${branch}) ──"
	sha=$(upstream_head "$url" "$branch")
	echo "    upstream HEAD: ${sha}"
	fetch_upstream "$url" "$branch" "${WORK}/${slug}"
	filter_and_copy "${WORK}/${slug}" "${SNAPSHOT_DIR}/${slug}" "${paths}"

	# Write a tiny pointer file so a reader can map this snapshot back
	# to the exact upstream commit it was taken from.
	cat >"${SNAPSHOT_DIR}/${slug}/.snapshot.json" <<EOF
{
  "upstream": "${url}",
  "branch": "${branch}",
  "sha": "${sha}",
  "synced_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "paths": "${paths}"
}
EOF
done

echo
echo "==> Summary"
for entry in "${UPSTREAMS[@]}"; do
	IFS='|' read -r slug _ _ _ <<<"$entry"
	if [[ "$FILTER" != "all" ]] && [[ "$FILTER" != "$slug" ]]; then
		continue
	fi
	diff_summary "$slug"
done

echo
echo "Review the delta with: git diff -- ${SNAPSHOT_DIR}"
echo "Stage with: git add ${SNAPSHOT_DIR}"
