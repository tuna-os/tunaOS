# RFC 011: Spec-driven work with Spektacular

- **Status:** Merged, with the approval of the maintainer: roll it out if the prototype works well. Decision recorded in [ADR 0010](../adr/0010-spec-driven-work-with-spektacular.md)
- **Issue:** [#2673](https://github.com/tuna-os/tunaOS/issues/2673)
- **Branch:** `rfc011-spektacular`
- **Owner:** hanthor
- **Tool:** [Spektacular](https://github.com/hivecommons/spektacular) 0.20.0, Apache-2.0

## Problem

Most changes to tunaOS start from an agent. The hive files issues. Claude,
Codex and Gemini sessions open pull requests. The agents do the work well
enough. The weak part is what they start from and what they leave behind.

- **Nobody keeps the intent in one place.** It sits in an issue, a PR or a
  chat. A PR can pass CI and still
  miss what the issue asked for. On 2026-09-24, #2660 said "Closes #2395" and
  shipped one of the three things that issue asked for.
- **Lessons do not reach the next agent.** `docs/ci-troubleshooting.md` holds
  more than 40 root causes, and `docs/adr/` holds 9 decisions. An agent reads
  them only if it knows to look. Row 42 of the table is the fourth instance of
  one defect in one file.
- **Nobody reviews the plan before the code.** An agent designs and codes in
  one pass. A reviewer sees the design for the first time in the diff, when it
  costs the most to change.

## Proposal

Use Spektacular for work that needs a plan. Spektacular is a single Go binary.
It runs three workflows as state machines:

1. **Spec.** An agent interviews the owner and writes `spec.md`: overview,
   requirements, constraints, acceptance criteria, technical approach, success
   metrics and non-goals.
2. **Plan.** The agent researches the code and writes `plan.md`,
   `research.md` and `context.md`. The plan is a document a person can review
   before any code exists.
3. **Build** (`spektacular implement`). The agent works through the plan phase by phase and checks
   the acceptance criteria.

A knowledge base under `.spektacular/knowledge/` holds conventions, a
glossary, gotchas, architecture notes, learnings and decisions. Every plan
loads the conventions and the glossary, and searches the rest. This gives the
lessons in `docs/ci-troubleshooting.md` and `docs/adr/` a path into every plan.

Spektacular comes from Hive Commons, the project that runs the hive agents on
this repository. It installs skills for Claude Code, Codex and Bob.

### When to use it

| Change | Spektacular |
|---|---|
| Needs an RFC under [RFC-PROCESS.md](../../RFC-PROCESS.md) | Required: spec and plan |
| Touches more than one area, or ports work between branches | Recommended |
| A single script fix or manifest edit | Not needed |

## Options considered

| Option | For | Against |
|---|---|---|
| **Spektacular** (chosen) | One binary with no runtime. Works with Claude, Codex and Bob. The knowledge base is plain Markdown in git. The Hive project that runs our agents maintains it. | Early: 0.20.0, about 20 stars. The workflows are long. |
| [GitHub Spec Kit](https://github.com/github/spec-kit) | Very popular. Many commands. | Needs Python 3.11 and `uv`. Built around Copilot. Has no knowledge base that plans must load. |
| [arittr/spectacular](https://github.com/arittr/spectacular) | Runs tasks in parallel worktrees and stacks the PRs. | Needs `git-spice` and a second plugin. Claude only. |
| No tool; use `docs/rfc/` only | No new dependency. | Does not fix the problems above: lessons still reach agents only by chance. |

## Prototype

On 2026-09-24 an agent ran all three workflows on a real change: #1893, the
tacklebox `podman commit` that stalls when an ISO build runs rootless. The
work ports two commits from `v4`. One passes the `TBOX_*` variables through
(#2507). The other adds the commit deadline and a pin bump (#2598). The run log is in
`.spektacular/plans/20260924185724-68c5afaf-tacklebox-commit-deadline/`.

| Step | Time | Output |
|---|---|---|
| Seed the knowledge base | 14 min | 45 entries: 14 conventions, 10 glossary, 12 gotchas, 9 decisions. Each cites its source file. |
| Spec | 10 min | `spec.md` with 6 acceptance criteria |
| Plan | 12 min | `plan.md`, `context.md`, `research.md` (390 lines in total) |
| Build | 9 min | 7 files and a regression test. 132 pytest and 45 bats tests pass |

**What worked.** In the discovery step, the agent made five checks of facts that the
brief took for granted. Each check found a fault:

- The #2598 commit is not on `v4`. It is only on the unmerged PR branch.
- tacklebox falls back to 600 seconds on a bad value, so the check on the
  tunaOS side is necessary.
- The adapter's fallback SHA is older than the minimum version it needs.
- `sudo --preserve-env=<list>` in `publish-iso-groups.yml` drops the `TBOX_*`
  overrides. The knowledge base had a gotcha about this:
  `sudo-resets-env-and-path`.
- Every CI ISO workflow builds tacklebox from source, so CI needs the new
  pin. The variables alone do not fix it.

The knowledge base changed the result. Two conventions added work that the
spec had left out: a row in `docs/ci-troubleshooting.md` for each diagnosis,
and a regression test with a Falsification line. At the end, `reconcile_spec` made the agent
report that 2 of 6 acceptance criteria are not met yet, because they need a
post-merge ISO build. Without that step the agent would have reported done.

**What did not work.**

- **Ceremony.** The plan is 196 lines for a change of about 50 lines. The
  build runs 6 steps per phase, and it writes three changelogs for one change.
- **Defaults for Go projects.** The `test` step tells the agent to write
  `*_test.go` files, and `verify` suggests `make test`. tunaOS uses bats,
  pytest and `just`.
- **Gates that expect a person.** The walkthrough, knowledge capture and
  verify steps each wait for a user to confirm. An agent that runs alone must
  approve its own work, and only a note records that it did.
- **Defects in 0.20.0.** The `assemble` scaffold comes out HTML-escaped.
  `write_research` deletes the files of the spec step, because the spec and the
  plan share a name. `plan file read` returns Markdown where every other
  command returns JSON.
- **Search.** `knowledge search` does not return `conventions/` or
  `glossary/` entries. Those are always loaded into a plan, but an agent
  that searches for them finds nothing.

**Verdict.** It works well enough to adopt, but only for the changes that the
table in [When to use it](#when-to-use-it) names. On a change that needs a
plan, the faults came to light in the discovery step and in the reconcile step. A direct agent
run would have shipped those faults.

## Rollout

1. **Commit the project files.** `.spektacular/config.yaml`, the 45-entry
   knowledge base, and the #1893 spec and plan as the worked example.
2. **Commit the skills.** `.gitignore` ignores `.claude/`. Add an exception
   for `.claude/skills/spek-*/`, so every Claude session gets the workflows.
3. **Keep AGENTS.md short.** `spektacular init` appended 349 lines to
   `AGENTS.md`. Replace them with a section of about 20 lines that points to
   the skills and the table above. `spektacular migrate` does not put the
   lines back.
4. **Tell it how tunaOS tests.** Add a convention entry for the test commands:
   `just check`, the bats suites and the pytest suites. The entry also tells
   agents to ignore the Go defaults in the `test` and `verify` steps.
5. **Pin the version.** Add `spektacular: "v0.20.0"` to `image-versions.yaml`
   with a Renovate comment, as for the other tools.
6. **Report the defects upstream.** File each defect above on
   hivecommons/spektacular. Also ask for an unattended mode that records who
   approved each gate.
7. **Record the decision.** [ADR 0010](../adr/0010-spec-driven-work-with-spektacular.md).

The #1893 change itself is in its own PR, [#2682](https://github.com/tuna-os/tunaOS/pull/2682), so that a reviewer can judge it apart
from the tool.

## Risks

- **An early tool.** Spektacular is at 0.20.0 and can change its file
  formats. `spektacular migrate` upgrades a project, and `spektacular version
  check` reports a mismatch. We pin the version in `image-versions.yaml`, as
  we do for every other tool.
- **Cost per change.** The plan workflow has 20 steps. For a small change this
  is more work than the change. The table above keeps small changes out.
- **A stale knowledge base is worse than none.** Plans treat an entry as
  truth over the code. Each entry must cite the file it comes from, so a
  reviewer can check it.

## Revert

Remove `.spektacular/`, the `spek-*` skills and the Spektacular section of
`AGENTS.md`. No build, image or CI job depends on it.
