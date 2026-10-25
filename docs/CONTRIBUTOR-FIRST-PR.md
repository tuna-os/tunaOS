# Your first TunaOS contribution

Choose one task below. Each task changes docs, needs no bootc
knowledge, and should take 45–90 minutes after tool setup. Stop and ask
on the issue if it takes longer; a reviewer can split the task.

These tasks support [#3117](https://github.com/tuna-os/tunaos/issues/3117).
Check the linked issue's state, assignees, claim comments, and linked PRs
before you start. A link here is not a promise that a task is still free.
If each task has a contributor, use the [live starter search](https://github.com/tuna-os/tunaos/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

## Five small tasks

Each issue has the full scope, checks, branch name, and review contact.
All branches start at `upstream/main` and target `tuna-os/tunaos:main`.

| Task | Problem and acceptance criteria | Starter branch | Time |
|---|---|---|---|
| [Git terms](https://github.com/tuna-os/tunaos/issues/3749) | Define fork, clone, origin, upstream, branch, commit, PR, and review in the ecosystem guide. Link the terms from the fork workflow. | `docs/contributor-git-terms` | 45 min |
| [First documentation edit](https://github.com/tuna-os/tunaos/issues/3750) | Add a worked example to CONTRIBUTING: find one broken local link, change its target, check it, and submit a focused PR. Use a fictional example, not a new product claim. | `docs/first-doc-edit` | 60 min |
| [Safe bug report](https://github.com/tuna-os/tunaos/issues/3751) | Add a fictional report with expected/actual results, reproduction steps, version, and redacted log output. Link SECURITY.md for private reports and index the example. | `docs/bug-report-example` | 60 min |
| [Local test guide](https://github.com/tuna-os/tunaos/issues/3752) | Add a local-check entry point to TESTING.md. Separate lint, unit tests, and VM checks; cite the recipes and show one focused existing test command. | `docs/local-test-guide` | 90 min |
| [Review feedback](https://github.com/tuna-os/tunaos/issues/3753) | Add a worked review exchange to the ecosystem guide: clarify a request, make a signed-off follow-up commit, rerun checks, and push to the same PR. | `docs/review-walkthrough` | 60 min |

## From claim to review

1. Comment on one issue with the task you want and any setup questions.
   Check for an existing claim first. You can ask for a mentor with the
   [mentor request](../CONTRIBUTING-ADVANCED.md#request-and-accept-a-pairing).
2. Fork and clone the repository. The commands below need Git and GitHub CLI.
   Authenticate GitHub CLI with your own account; keep credentials private.

   ```bash
   gh repo fork tuna-os/tunaos --clone=true
   cd tunaos
   git remote -v
   git fetch upstream
   git switch -c docs/my-first-change upstream/main
   ```

   Use the directory that the clone command prints if its letter case differs.
   `origin` must be your fork; `upstream` must be `tuna-os/tunaos`.
   If `upstream` is absent, add it with
   `git remote add upstream https://github.com/tuna-os/tunaos.git`.
3. Read [the contributor guide](../CONTRIBUTING.md) and the issue. Install the check
   tools with `just setup`, then edit only the files in the agreed scope.
   Check claims with the [content checklist](CONTENT-CLAIM-CHECKLIST.md).
4. Run `just fix`, `just check`, `just ste`, and `git diff --check`.
   Read `git diff` before you stage files. If a check cannot run, include
   its command and error in the PR. Ask for help with the failure.
5. Set your Git author name and email. Commit with `git commit -s` so the
   Signed-off-by email matches your author email. Stage only your changed
   files, then push the branch to your fork:

   ```bash
   git add path/to/changed-file.md
   git commit -s -m "docs: explain the first contribution step"
   git push -u origin HEAD
   gh pr create --repo tuna-os/tunaos --base main
   ```

   In the PR body, link the task with `Closes #TASK_NUMBER` only when its
   full scope is complete. List checks and failures. Open ready for review.
6. Respond on the PR and push follow-up commits to the same branch.
   Expect an acknowledgement or status update by the next
   [weekly triage](../CONTRIBUTING.md#weekly-contributor-triage), not a merge
   deadline. Use the [review help path](../CONTRIBUTING-ADVANCED.md#review-response-target-and-escalation)
   if that slot passes without a response. A maintainer handles merge.

The review contact is James Reilly ([@hanthor](https://github.com/hanthor)),
the [listed maintainer](../MAINTAINERS.md). A mentor or reviewer must
accept on the issue before you name them as the owner. Do not assign another
person's time. Matrix is optional; keep decisions and next steps on GitHub.

## Keep the track useful

At weekly triage, check all five issue links. Replace completed tasks with
bounded work, and check open PRs before filing a replacement. Apply both
`good first issue` and `help wanted`; the hyphenated Hive labels are different.
Use the `Q4 Community Growth` milestone. Ask a human reviewer to accept the
task and record the next check-in on its issue. Agents should leave these
starter tasks for new human contributors; report a stale task during triage.

Track claim → first response → PR → merge → repeat contribution with dated
GitHub links. Use [ADOPTION-METRICS](../ADOPTION-METRICS.md) for the monthly
human-contribution count; a seeded issue or agent PR does not meet that goal.

### Publication handoff

On 2026-10-23, this contribution created issues #3749–#3753. GitHub rejected
the label updates with `AddLabelsToLabelable` permission errors. The issue reads confirmed no labels, milestone, or assignee. The
contributor API write gate also rejected creation of `Q4 Community Growth`.
These tasks have direct links above but do not yet appear in the labelled pool.

A maintainer must create that milestone through the repository's
[milestone page](https://github.com/tuna-os/tunaos/milestones), then apply it
and both labels to the five issues. An authorized maintainer can run:

```bash
gh issue edit 3749 3750 3751 3752 3753 --repo tuna-os/tunaos \
  --add-label 'good first issue,help wanted' --milestone 'Q4 Community Growth'
```

After the updates, check each issue and the public label search. Ask a human
to accept review of each task on its thread. The current review contact
does not establish an accepted assignment. Keep #3117 open for these actions
and the live-session and publication follow-up in the
[roadmap](CONTRIBUTOR-ROADMAP.md).
