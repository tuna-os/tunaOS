# --- CI recipes called from workflows: misc ---
# Each recipe is a workflow step moved out of YAML so it can be run and tested locally.
# Recipe names are prefixed ci- (just imports share one flat namespace).

# snapshot-upstreams.yml: report whether _upstream-snapshots/ moved; writes has_diff and summary to $GITHUB_OUTPUT
ci-snapshot-detect-changes:
    #!/usr/bin/env bash
    set -eu
    cd {{ justfile_directory() }}
    # Deliberately no `pipefail` (the workflow step ran under `bash -e`):
    # `git status | grep -q .` exits at the first line, and a SIGPIPE'd `git`
    # must not flip "changes found" into "nothing to PR".
    if git status -s -- _upstream-snapshots/ | grep -q .; then
      echo "has_diff=true" >> "$GITHUB_OUTPUT"
      # Capture a compact one-page-ish view of the delta for the
      # PR body — full diff will live in the PR itself.
      {
        echo "summary<<EOF"
        echo '```'
        git diff --stat -- _upstream-snapshots/ | head -50
        echo '```'
        echo "EOF"
      } >> "$GITHUB_OUTPUT"
    else
      echo "has_diff=false" >> "$GITHUB_OUTPUT"
      echo "No upstream changes — nothing to PR."
    fi

# snapshot-upstreams.yml: commit _upstream-snapshots/ to a dated branch and open or update its PR (env: GH_TOKEN, DIFF_SUMMARY, GITHUB_REPOSITORY)
ci-snapshot-open-pr:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}
    DATE=$(date -u +%Y-%m-%d)
    NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    BRANCH="upstream-snapshots/${DATE}"
    # Stable branch per-week so re-runs the same week reuse it. The
    # checkout action starts from the default branch and does not fetch
    # arbitrary remote branches, so fetch the existing branch before
    # using force-with-lease below. Without this, a same-week rerun can
    # fail even though the branch and PR are both still valid (#1194).
    if git ls-remote --exit-code origin "refs/heads/${BRANCH}" >/dev/null 2>&1; then
      git fetch --no-tags origin \
        "refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}"
      git checkout -B "$BRANCH" "origin/$BRANCH"
    else
      git checkout -b "$BRANCH"
    fi
    git add _upstream-snapshots/
    if git diff --cached --quiet; then
      echo "Nothing staged after add — skip"
      exit 0
    fi
    # Write the commit message to a file to avoid multi-line-string headaches.
    MSG=$(mktemp)
    printf 'chore(snapshots): refresh upstream tree snapshots\n\nRun at %s. See _upstream-snapshots/<repo>/.snapshot.json for the\nexact upstream commit each path was taken from.\n\nThis diff IS the catch-up review surface — content-level, no\ncommit-message noise.\n' "$NOW" > "$MSG"
    git commit -F "$MSG"
    rm -f "$MSG"
    git push --force-with-lease origin "$BRANCH"

    # PR body: similarly written via a temp file.
    BODY=$(mktemp)
    {
      echo "## Weekly upstream snapshot refresh"
      echo
      echo "Content delta between last week's snapshot and current upstream state (Aurora, Bluefin-LTS, Zirconium)."
      echo
      echo "### Stat"
      echo
      echo "${DIFF_SUMMARY}"
      echo
      echo "### Next step"
      echo "- Skim the diff. feat/fix to build pipeline (package list, service flip, config) is a porting candidate."
      echo "- Open a separate PR with the port. Once it lands, merge this one to update the baseline."
    } > "$BODY"

    if gh pr view "$BRANCH" --repo "${GITHUB_REPOSITORY}" &>/dev/null; then
      gh pr edit "$BRANCH" --repo "${GITHUB_REPOSITORY}" --body-file "$BODY"
    else
      gh pr create \
        --repo "${GITHUB_REPOSITORY}" \
        --base main \
        --head "$BRANCH" \
        --title "chore(snapshots): refresh upstream tree (${DATE})" \
        --label "upstream-snapshot" \
        --body-file "$BODY"
    fi
    rm -f "$BODY"
