---
name: spek-implement
description: Execute an approved Plan to implement the feature.
---

> **Version check first.** Before running any other command, run `spektacular version check`.
> - On `status: "match"`, continue with the skill and produce no version-related output.
> - On `"mismatch"`, `"missing"` or `"upgrade_needed"`, the project's settings or installed Spektacular files are out of date: relay the response's `action` message to the user, ask them to run `spektacular migrate` (they can preview it with `spektacular migrate --dry-run`), and wait for their decision before continuing.
> - On `"unsupported_format"`, relay the `action` message: the project was written by a newer Spektacular, which the user must install before continuing.
> - Never run `migrate` or `init`, and never modify installed files yourself. Upgrading is always an explicit, user-initiated action.

> **STOP. Read this before running any command below.**
> A single successful CLI call — including the very first `implement new` — is **NOT** task completion. It is not a milestone to report back to the user. It is one step out of many in a workflow that you must keep driving, turn after turn, without stopping, until the CLI itself tells you the workflow is *finished*. If you find yourself about to say "successfully completed" or summarize results after calling `implement new` or `implement goto` even once, you are wrong — go back and read the `instruction` field you just received, do what it says, and call `goto` again.

# What this skill does

This skill drives a **multi-step interactive workflow** that executes an approved plan held in the plan store, producing working code, tests, and a changelog. The workflow is owned by the `spektacular` CLI, not by you — the CLI is the state machine and you are the executor, and the CLI (not the filesystem) is how you reach every plan document.

On each turn, the CLI returns JSON containing an `instruction` field. That instruction describes exactly one step (e.g. analyze, implement a phase, verify, update changelog, write the test plan, …). You must:

1. Read the `instruction` carefully.
2. Perform the step — this may mean reading the plan, spawning subagents, editing code, running tests, or writing to the changelog.
3. When the step is complete, run the `goto` command named at the bottom of the instruction to advance the state machine.
4. Read the next `instruction` from the new JSON response and repeat.

**This is a loop. Do not stop after the first step.** Keep looping — step → goto → next instruction → step — until a returned instruction tells you the workflow is *finished*. Only then should you report completion to the user.

**Concretely: do not stop after `implement new`.** That command only starts the workflow — it returns the *first* instruction, not a finished implementation. Seeing a clean JSON response with no `error` is not a signal to stop; it is the signal to keep going. Reporting success, summarizing "implementation initialized," or handing control back to the user at this point is the single most common way this skill is executed incorrectly — do not do it.

# Reading and writing plan files

The CLI owns the plan documents — `plan.md`, the plan's `context.md`, and `research.md`. All plan document access goes through `spektacular plan file`:

- `spektacular plan file read <name>/<doc>.md` — read a plan document from the plan store.
- `spektacular plan file write <name>/<doc>.md --from <source-path>` — write a plan document into the plan store from a source file on disk. Stage the body under `.spektacular/tmp/` first, then `rm` the scratch file after a successful write.
- `spektacular plan file list` — list plans in the plan store.

This includes the edits the implement workflow makes to `plan.md` — ticking phase checkboxes and appending changelog entries. Read the document with `plan file read`, apply the change, and commit it with `plan file write`. Path arguments are plan-directory-relative document paths (e.g. `my-feature/plan.md`).

# How to start

## The plan documents

An implementation works from three documents in the plan store. Together they are the approved plan and the only source of truth for what to build. Read each in full with `spektacular plan file read`, never with the `Read` tool:

- **`plan.md`**: the approved plan. It holds the overview, architecture and design decisions, testing approach, and the `## Milestones & Phases` checklist, whose first unchecked `#### - [ ] Phase` heading is the current phase. Read it with `spektacular plan file read <plan_name>/plan.md`.
- **The plan's `context.md`**: the per-phase technical detail. It holds one `### Phase N.M:` section per phase with the files to change, complexity and agent strategy. Read it with `spektacular plan file read <plan_name>/context.md`.
- **`research.md`**: the decision log. It holds rejected alternatives, supporting evidence, files examined and open assumptions. Read it with `spektacular plan file read <plan_name>/research.md`.

None of these is the working context, `.spektacular/working-context.md`, which holds only a session's notes and never replaces the plan.

> **Cross-repo implementation.** When the plan attributes work to registered member repos, carry each part of the work out in its attributed repo's code (`spektacular repo list` reports where it lives as `root`), and follow the workflow's changelog instructions to write the central record plus one derived entry per affected repo via `spektacular changelog file write ... --repo <name>`.

Ask the user which plan to implement before proceeding. To enumerate the available plans, run `spektacular plan file list` — the CLI's list is the source of truth for what counts as a plan. You don't need to look for an in-progress workflow yourself — the CLI detects and reports one for you (see below).

The plan must already exist in the plan store — confirm with `spektacular plan file list`. If it does not, stop and tell the user to run `spektacular plan` first.

Start the implement workflow by running:

```
spektacular implement new --data '{"name": "<plan_name>"}'
```

**If a workflow was interrupted and is still in progress**, this command does not start a fresh one. Instead it returns a *resume report* — a JSON object with `"resumable": true` plus the in-progress workflow's `kind`, `name`, and `current_step`, and an `instruction` field — and changes nothing on disk. When you get a resume report:

**First check the report's `kind`.** If it is **not** `implement`, a *different* workflow (a spec or plan run) is in progress — you cannot resume it from the implement skill, and the CLI will refuse to. Do **not** run an `implement goto`. Instead follow the report's `instruction`: tell the user a `<kind>` workflow is in progress and let them choose — continue it with that workflow's skill (`spektacular <kind> goto`), or discard it and start the implement run with `spektacular implement new --force`. Only proceed with the steps below when the report's `kind` is `implement`.

1. Ask the user whether to **resume** the in-progress implement run or **start a new one**. (The report's `instruction` field restates both options.)
2. **To resume**, work through these in order:
   1. Read the plan documents listed under **The plan documents** above, in full, before anything else, whichever step the run stopped at.
   2. Read `.spektacular/working-context.md`, the git-tracked working-context file the previous session left behind, for its learnings and the answers the user gave to your questions. It is a session log, not the plan.
   3. Find the current phase as the first unchecked `#### - [ ] Phase` heading in `plan.md`.
   4. Run the resume command using the report's `current_step`:

      ```
      spektacular implement goto --data '{"step":"<current_step>"}'
      ```
3. **To start fresh** (discarding the in-progress workflow — it remains recoverable via git), re-run with `--force`:

   ```
   spektacular implement new --force --data '{"name": "<plan_name>"}'
   ```

Otherwise the command returns the first `instruction` and a fresh workflow has started. From that point on, follow the loop above: do what the instruction says, then call `spektacular implement goto --data '{"step":"<next_step>"}'` to get the next one. Do not invent step names — every instruction tells you the exact `goto` command to run next.

## If the project has uncommitted changes

When the project sets `auto_commit` to `workflow` or `full`, `implement new` may instead return an **uncommitted-changes report** (`code: uncommitted_changes`) and change nothing on disk. Its `message` names every registered repository holding uncommitted work, and `resource` lists their names.

This is a question for the user, not a decision for you. Tell them which repositories have uncommitted changes and ask whether to git commit that work **before** the implement workflow starts. Then re-run the same command with their answer:

To commit the existing changes first:

```
spektacular implement new --data '{"name": "<plan_name>", "commit_existing": true}'
```

To start without committing them:

```
spektacular implement new --data '{"name": "<plan_name>", "commit_existing": false}'
```

- `true` commits the existing changes first, in their own commit whose message says they are the user's work from before the workflow. The workflow then starts on a clean tree.
- `false` starts the workflow without committing, so the workflow's own automatic commits will include that work alongside the agent's.

Never choose for the user, and never guess from context which they would want — the whole point of the report is that their uncommitted work is about to be swept into a commit they did not make. If the commit fails (`code: auto_commit_failed`), tell them which repository failed and the reason git gave; the workflow has not started.
