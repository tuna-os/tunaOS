---
name: spek-design
description: Author, bring in, revise or reference a design document.
---

> **Version check first.** Before running any other command, run `spektacular version check`.
> - On `status: "match"`, continue with the skill and produce no version-related output.
> - On `"mismatch"`, `"missing"` or `"upgrade_needed"`, the project's settings or installed Spektacular files are out of date: relay the response's `action` message to the user, ask them to run `spektacular migrate` (they can preview it with `spektacular migrate --dry-run`), and wait for their decision before continuing.
> - On `"unsupported_format"`, relay the `action` message: the project was written by a newer Spektacular, which the user must install before continuing.
> - Never run `migrate` or `init`, and never modify installed files yourself. Upgrading is always an explicit, user-initiated action.

# What this skill does

This skill handles the four ways a design document enters a project: helping the user work one
out that does not exist yet, bringing in one they already have, revising one that exists, and
recording a reference to one already stored. Unlike `spek-new`, `spek-plan` and `spek-implement`,
it does not drive an interactive CLI state machine — it is a static playbook. That is deliberate
and load-bearing: a state machine could not run inside a spec workflow, and design conversation
happens during one. The agent recognises which situation the user is in, picks one of four
branches, and calls the matching `spektacular design` command directly.

Two classes of design document exist and the difference matters at every branch. A design the
project already had is stored exactly as supplied and never gains anything. A design Spektacular
authors with the user carries the same lifecycle record every spec and plan carries, so it
reports where it stands, which spec's conversation produced it, and which specs reference it.

# When to invoke

Invoke this skill whenever a design document is in play. Typical natural-language triggers:

- "Help me write this up as a design." / "Can you turn this into a design document?"
- "I already have a design for this, can you store it?" / "Here is our API design doc."
- "That design has changed." / "Update the retry design to cover timeouts."
- "Point this spec at the design we already have."

One skill handles all four intents. Discriminate by what the user actually said. If it is genuinely
unclear whether they already have the document written, ask that one question — it is the only
thing separating the author branch from the bring-in branch.

Before any branch that names a source, run `spektacular design sources` to see the declared
sources and their locations. Choose only from the names it returns, never a name you inferred.
`spektacular design list` shows what those sources already hold, including which documents carry a
lifecycle record and which do not.

# Intent: author

Triggered when the design has been worked out in conversation, or needs to be, and nothing is
written down yet. This branch runs an interview and then writes the document from it.

**Run the interview before drafting anything.** It follows the Flipped Interaction pattern (White
et al., "A Prompt Pattern Catalog to Enhance Prompt Engineering with ChatGPT," arXiv:2302.11382),
the same pattern the spec workflow's own interview uses: rather than asking the user to author the
document from a blank prompt, you drive the conversation with a stated goal, adaptive questions
toward it, and an explicit stopping condition.

**Stated goal:** understand the design well enough to write a document someone could build from.

**Ask adaptive, open questions — not a fixed script.** Start from what the user has already said.
Ask about the shape of the thing being designed, what it does in the ordinary case, what it does
at the edges, what it deliberately does not do, and which parts are settled versus still open.
Each question should follow from the answer before it, pursuing what is still unclear rather than
working through a checklist.

**Stop once a further answer would not change the document.** That is the stopping condition, and
it is a rule rather than a suggestion. Test it directly: ask yourself whether another answer would
change what you write. When the answer is no, stop and draft. This should take a small number of
exchanges. If the user's description already settles the design, a short interview or none at all
is correct — do not manufacture questions for their own sake.

**Write the design, not the conversation.** The document records the decisions, not the
back-and-forth that produced them, and it is the size of the design rather than the size of the
discussion. A transcript is a failure of this branch even when every fact in it is accurate.

**Do not impose a structure.** There is no template and no required headings. The document's shape
follows the design.

Then:

1. Present the draft to the user as ordinary readable text, in full, and get their explicit
   agreement before writing anything.
2. Stage it under `.spektacular/tmp/<slug>.md` with your own `Write` tool.
3. Write it:
   ```
   spektacular design author --data '{"source":"<name>","path":"<path>"}' --from .spektacular/tmp/<slug>.md
   ```
   Add `--spec <spec name>` when the conversation belonged to a spec, which records where the
   design came from. Add `--document-status <draft|final|superseded|archived>` to set its
   lifecycle status; it defaults to `draft`.
4. `rm .spektacular/tmp/<slug>.md`.
5. **Only if a spec exists**, record the reference on it:
   ```
   spektacular design ref add --data '{"spec":"<spec>","source":"<name>","path":"<path>"}'
   ```
   A design can be authored before any spec exists. When there is no spec, stop after step 4 —
   there is nothing to reference it from yet, and that is a complete outcome rather than a
   half-finished one.

# Intent: bring in

Triggered when the user already has the design written and wants it stored. There is no interview:
the document exists, and the work is to store it without disturbing it.

1. Confirm with the user which declared source it belongs in and the path within it.
2. Write it:
   ```
   spektacular design write --data '{"source":"<name>","path":"<path>"}' --from <path to their file>
   ```
   This stores the bytes exactly as supplied. Nothing is added, removed, reordered or
   reformatted, and the document gains no frontmatter, so it reads back byte for byte identical.
   That guarantee is the whole point of this branch: a design the team wrote stays theirs.
3. Record the reference with `spektacular design ref add` if a spec should point at it.

Do not use `design author` here. Authoring stamps a lifecycle record, and a document the user
handed over is not one Spektacular wrote.

# Intent: revise

Triggered when a design that already exists has changed.

1. Read the current document: `spektacular design read --data '{"source":"<name>","path":"<path>"}'`.
2. Establish what changed. If the conversation has already settled it, do not re-interview; if it
   has not, run the author branch's interview on the delta alone rather than on the whole design.
3. Present the revised document to the user in full and get their explicit agreement.
4. Rewrite it with `spektacular design author`, exactly as in the author branch. For a document
   Spektacular authored this is an update in place: it keeps the document's original capture date
   and the specs already referencing it, so existing references keep resolving. Pass
   `--document-status superseded` if the design has been replaced rather than amended.

If the document is one the project already had, and so carries no lifecycle record, revise it with
`spektacular design write` instead, which again stores the bytes exactly as supplied.
`spektacular design list` tells the two apart: a document Spektacular authored reports its status
and capture date, one the project already had reports only a source and a path.

# Intent: reference only

Triggered when the document is already in a declared source and all that is missing is the link
from a spec.

```
spektacular design ref add --data '{"spec":"<spec>","source":"<name>","path":"<path>"}'
```

Recording a reference keeps both documents in agreement: the spec gains the reference, and a design
Spektacular authored gains the spec in its own record. A design the project already had takes part
without being touched. `spektacular design ref list --data '{"spec":"<spec>"}'` reports what a spec
already references and whether each reference resolves, and `spektacular design ref remove` drops
one from both sides.

# Decline handling

Nothing is written without the user's explicit agreement. Every branch that writes presents its
document or its proposal first and waits.

If the user declines, asks for changes, or expresses uncertainty at any propose-then-confirm
checkpoint, **do not invoke `spektacular design author` or `spektacular design write`**. Either
loop back and refine the draft, or stop and leave the source untouched. Remove any staged scratch
file at `.spektacular/tmp/<slug>.md` either way; a half-finished proposal should not linger on
disk.

A decline is final for that design, not a "not now": do not raise it again for the same detail
later in the conversation. It also means the detail does not get smuggled into the spec body
instead — it stays out, or it stays as the one-line steer it already was.

The propose-then-confirm contract is enforced by this prose, not by a CLI guard. Treat it as
load-bearing: a write without explicit user approval is a bug in the skill's execution, not an
acceptable shortcut.
