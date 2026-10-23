# Contributing across the TunaOS ecosystem

Start with [CONTRIBUTING.md](CONTRIBUTING.md) for the fork workflow and
required checks. This guide helps you choose a repository, ask for a mentor,
and progress from a first contribution to helping other contributors.

## Git terms

These terms describe the [fork workflow](CONTRIBUTING.md#fork--pr-loop)
for this project.

| Term | Meaning in this project |
|---|---|
| Fork | A fork is your copy of `tuna-os/tunaos` on GitHub, where you can push changes. |
| Clone | A clone is a local copy of a repository and its Git history, such as the copy of your fork on your computer. |
| Origin | `origin` is the remote name for your contributor fork in the local clone. |
| Upstream | `upstream` is the remote name for the source repository, `tuna-os/tunaos`, in the local clone. |
| Branch | A branch is a named line of work, such as `docs/my-first-change`, that keeps your commits separate from `main`. |
| Commit | A commit is a saved snapshot of the files Git tracks, with an author and a message that describes the change. |
| Pull request (PR) | A pull request asks maintainers to merge changes from your fork's branch into `tuna-os/tunaos:main`, the PR base branch. |
| Review | A review is feedback on a pull request to check its changes and decide whether it is ready to merge. |

## Find the right repository

Follow the change through its producer and consumer before opening a PR.
An image-factory change does not automatically update a separate installer,
package source, or documentation site. Read each target repository's own
contribution guide, base-branch rules, and checks; do not copy this repo's
`just` commands into another project without checking them.

| Area | Where to start | Boundary to check with a reviewer |
|---|---|---|
| Image composition and desktop manifests | [tunaos](https://github.com/tuna-os/tunaos), [architecture guide](docs/AGENT_GUIDE.md) | Package selection, build stages, and image qualification belong here. |
| Package production | [tunaos-packages](https://github.com/tuna-os/tunaos-packages), [sourcing policy](PACKAGE-SOURCING.md) | Separate producing a package from selecting it for an image. |
| Separate desktop images | [tromso](https://github.com/tuna-os/tromso), [xfce-linux](https://github.com/tuna-os/xfce-linux) | These have their own BuildStream builds and qualification, outside this repo's matrix. |
| Installation | [bootc-installer](https://github.com/tuna-os/bootc-installer), [fisherman](https://github.com/tuna-os/fisherman), [iso-builder](https://github.com/tuna-os/iso-builder) | Identify whether the failure is in the UI, installation pipeline, or media generation. |
| Windows bootc workflow | [wootc](https://github.com/tuna-os/wootc) | Use its platform prerequisites and tests. |
| User documentation | [docs](https://github.com/tuna-os/docs), [claim checklist](docs/CONTENT-CLAIM-CHECKLIST.md) | Verify claims against the producing repository before publishing a guide. |

For other projects, browse the [organization repositories](https://github.com/orgs/tuna-os/repositories).
This is a routing map, not a promise that each project has mentors available.
For a change spanning repositories, link the issues and PRs in both directions,
state which change must land first, and give each repository its own validation.

## Choose a starter task

Use the [live org-wide starter pool](https://github.com/issues?q=org%3Atuna-os+is%3Aissue+is%3Aopen+archived%3Afalse+label%3A%22good+first+issue%22).
Narrow it with `repo:tuna-os/<name>`, for example:

- [Documentation](https://github.com/tuna-os/docs/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
- [Packages](https://github.com/tuna-os/tunaos-packages/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
- [Installer](https://github.com/tuna-os/bootc-installer/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
- [wootc](https://github.com/tuna-os/wootc/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)

An empty search means no labelled task is available there. Do not infer
availability from an old census. Check assignees and recent claim comments,
then leave your own claim and ask whether the scope is still available.
If no task fits, describe your interests and available test environment in
[Matrix](https://matrix.to/#/%23tunaos:reilly.asia) and ask for a bounded task.
Maintainers can use the [curation checklist](docs/HACKTOBERFEST-2026.md#curation-checklist)
and `scripts/gfi-pool-report.sh` to refresh the pool without copying live
counts into this guide.

## Mentorship ladder

These are voluntary learning steps, not titles or automatic repository access.
A contributor can stay at any step and decline mentoring work.

| Step | Practice | Evidence for the next step |
|---|---|---|
| First contribution | Reproduce one bounded issue with a volunteer mentor; submit a focused PR with checks. | Explain the change and address review feedback. |
| Repeat contributor | Take a second task in the same area; document a setup or testing lesson. | Independently reproduce, validate, and explain a change. |
| Review partner | With the author's agreement, review another starter PR for scope, reproduction, and tests. | Give actionable feedback and distinguish advice from merge requirements. |
| Mentor | Volunteer for one bounded task, agree availability, and help a newcomer through review. | Complete the pairing and record a useful handoff for the next mentor. |

Maintainers retain review and merge authority. Completing these steps does
not grant permissions; any role change follows the target project's process.

### Request and accept a pairing

On the issue or PR, post:

```text
Mentor requested
Task / PR:
Experience and what I want to learn:
Test environment:
Where I am stuck / help requested:
Availability and preferred async channel:
```

A volunteer replies on the same thread with the area they can help with,
the next check-in, and their capacity (start with one active pairing).
A request is unmatched until someone explicitly accepts it. Do not assign
another person's time. Keep decisions and reproduction steps on GitHub even
if troubleshooting happens in chat; avoid posting credentials or private logs.
If either person needs to stop, leave the current state, next action, and a
request for a new volunteer on the thread. A pause is not a failed contribution.

## Office hours and asynchronous questions

Use the existing [weekly contributor triage](CONTRIBUTING.md#weekly-contributor-triage)
as the place to collect Q&A and pairing requests. Post questions with issue
links in Matrix beforehand; contributors who cannot attend can ask for a
written answer on their issue or PR.

A volunteer hosting a live session should announce its date, UTC time,
duration, Matrix room, and topic in Matrix and link the announcement from
the relevant GitHub thread. Use an existing project chat rather than creating
a new server. Afterward, put decisions and next actions on the linked threads.
There is no fixed live office-hours time until a host announces one; the
README should link here instead of promising an unannounced session.

## Review response target and escalation

The existing target is an acknowledgement or status update by the next
weekly contributor triage slot. This is a response target, not a guaranteed
merge deadline or a new obligation for satellite maintainers. Ask the target
repository which review cadence it uses before assuming this one applies.

1. When opening a first PR, say it is your first contribution, link the task,
   include check results, and name any agreed mentor. Keep it ready for review
   only when the scoped change is complete.
2. If the next weekly triage passes without a response, leave one follow-up
   on the PR with the blocker and ask in Matrix with the PR link.
3. If another weekly cycle passes, ask in the same thread for a reviewer
   handoff or a smaller scope. A mentor can summarize the technical state;
   a maintainer decides review ownership and merge readiness.
4. When blocked on access, policy, or a dependent PR, record that dependency
   and the next action explicitly. Do not repeatedly ping or bypass checks.

At weekly triage, review unmatched requests and stalled first PRs alongside
the starter pool. Record the next responder and check-in only when they
accept. For retention measurement, use linked claims and PR timestamps for
time to first response, completed pairings, and repeat contributors; see
[adoption metrics](ADOPTION-METRICS.md). Do not publish a mentor roster or
attendance information without each person's consent.
