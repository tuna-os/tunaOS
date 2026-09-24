---
name: spek-knowledge
description: Search, contribute to, or update the project's knowledge base.
---

> **Version check first.** Before running any other command, run `spektacular version check`.
> - On `status: "match"`, continue with the skill and produce no version-related output.
> - On `"mismatch"`, `"missing"` or `"upgrade_needed"`, the project's settings or installed Spektacular files are out of date: relay the response's `action` message to the user, ask them to run `spektacular migrate` (they can preview it with `spektacular migrate --dry-run`), and wait for their decision before continuing.
> - On `"unsupported_format"`, relay the `action` message: the project was written by a newer Spektacular, which the user must install before continuing.
> - Never run `migrate` or `init`, and never modify installed files yourself. Upgrading is always an explicit, user-initiated action.

# What this skill does

This skill orchestrates the existing `spektacular knowledge` CRUD surface for ad-hoc read, contribute, update, audit, and maintenance operations on the project's knowledge store, without starting a spec/plan/implement flow. Unlike `spek-new`, `spek-plan`, and `spek-implement`, it does not drive an interactive CLI state machine — it is a static playbook. The agent recognises the user's natural-language intent, picks one of five branches (lookup / contribute / update / audit / maintenance), and calls the matching `spektacular knowledge` command directly.

# When to invoke

Invoke this skill any time the user references the knowledge base, an entry, a convention worth remembering, or asks a question that the knowledge store might already answer. Typical natural-language triggers include:

- "What do we know about X?"
- "Search the knowledge base for Y."
- "Remember that Z is the case." / "Add a note about Z."
- "Update what we have on W."
- "Recall the convention for V."
- "Check the tags on our entries." / "Are our knowledge entries tagged properly?"
- "Is the knowledge base still accurate?" / "Are these entries still true?" / "Review the knowledge base for anything out of date."

One skill handles all five intents. Discriminate by what the user actually said — do not ask the user to pick a slash command per intent.

# Intent: lookup

Triggered when the user wants to read or search existing entries. A lookup does **not** dump the raw hit list — it returns a single consolidated, source-cited answer with duplicates removed and every contributing store cited. The flow has a deterministic stage (exact de-dup) and a judgement stage (consolidation), kept strictly separate.

1. **Search.** Run `spektacular knowledge search <query>` with a concise query derived from the user's question. Narrow it with `--tier <project|repo|all>` and a repeatable `--filter <store>` when the question is about particular repos; omitting both covers every configured store. Add a repeatable `--tag <tag>` to restrict results to entries carrying a given tag — an entry lacking it is never returned, however well it would otherwise score, and repeating `--tag` narrows further rather than widening. The output is a ranked list of results — one per matching document, strongest match first — each carrying its `tier` and `name` (the store it came from), `path`, `title`, `score`, `category` (the kind of knowledge: e.g. `gotchas`, `architecture`, `learnings`), `checksum` (a content hash), `tags` (what the entry declares itself to be about, an empty list when it declares nothing), and up to three `excerpts`.

   **An entry does not have to contain every word of your query.** It is returned if it carries evidence for any of them, ranked on how much of the query it covers and how strongly. A tag match counts far more heavily than the same word appearing in the prose, so an entry tagged `go, http` is found by searching `go http router` even when its body contains neither word. Weak matches are dropped relative to the strongest hit, which means a loosely related entry surfaces when it is the only thing there and disappears once something genuinely relevant is present. Two consequences worth holding on to: a result is **not** proof that every query word appeared in it, and an empty result is **not** proof that nothing on the subject exists — try a differently-worded query before concluding the knowledge base is silent. If there are no hits, say so plainly and stop — do not fall back to a write unless the user explicitly asks to add a new entry.

2. **Exact de-dup (deterministic — no judgement).** Group the hits by their `checksum`. Hits sharing a checksum are byte-identical copies of the same entry held in more than one place; collapse each such group to a **single candidate**, unioning the `tier`/`name`/`path` citations of every copy in the group. This is pure equality — never merge two entries whose checksums differ at this stage, however similar they look. The result is a list of unique candidates, each with one or more source citations.

3. **Consolidate (judgement — delegated to a sub-agent).** Hand the unique candidates to a consolidation **sub-agent** so the raw bodies never crowd the main context. The sub-agent's contract:
   - **Input:** the user's question and the list of unique candidates (each with its `tier`, store `name`, `path`, and `category`).
   - **Task:** read each candidate's full body with `spektacular knowledge read --data '{"tier":"<tier>","name":"<name>","path":"<path>"}'`, then classify the *relationship* between candidates and combine them:
     - **Equivalent** (same point, different words) → merge into one point, citing every source.
     - **Refinement** (one is a more specific case of another) → keep both and say which is the narrower case. **There is no precedence between stores**: a repo's own store answers what is true of that repo's code, and the project's shared stores answer what spans repos. Neither overrides the other, so never silently drop one because of where it lives.
     - **Genuine contradiction** (sources actually disagree) → **surface it explicitly** as a conflict naming both stores; never silently drop or average it.
     - **Distinct** (unrelated points) → keep both.
   - **Output (returned to the main agent):** a single consolidated answer composed of merged points, **each citing the tier, store name and path** it was drawn from, with any contradictions presented as surfaced conflicts. The raw per-source candidate list is **not** the output.

4. **Present** the sub-agent's consolidated answer to the user, keeping every **citation (tier, store name and path) visible** so the user can see which configured store each point came from. Never present the raw hit list as the result.

**If the executing agent cannot spawn a sub-agent**, run the exact same consolidation inline in the main context instead: read the unique candidates' bodies, apply the identical relationship-classification rules, and present the same single cited answer. The output is identical; only the context isolation is weaker. Do not block on the absence of sub-agent orchestration.

# Intent: contribute

Triggered when the user wants to record something new.

1. Run `spektacular knowledge sources` to enumerate the configured stores by `tier` and `name`. That listing is the authoritative set of writable destinations and of valid `--filter` names: choose only from the names it returns, never a name you inferred. Run `spektacular knowledge categories` to load the category definitions — each category's purpose, boundary, retrieval tier, and expected entry shape. Run `spektacular knowledge tags` to load the tag vocabulary already in use, most-used first with a count of the entries carrying each. That listing is what keeps the vocabulary converging instead of fragmenting: it reports what exists, and choosing from it is your judgement.
2. **Route the entry to a category.** From the definitions, pick the category whose **Purpose** matches the entry and whose **Boundary** does not push it elsewhere — e.g. a standing rule is a `convention`, a defined term is a `glossary` entry, the reasoning behind a choice is a `decision`, an empirical finding is a `learning`, a structural fact is `architecture`, a sharp edge is a `gotcha`. Honour the **entry shape**: the `glossary` is for a term and a short gloss only — steer over-long or multi-paragraph content to a more fitting category (architecture, learnings, decisions) rather than letting it bloat the always-applied glossary. The entry's path is then `<category>/<slug>.md`, a slug-style filename under the chosen category.
3. **Choose the entry's tags.** Tags say what an entry is about, independently of the words its prose happens to use, and they are what will retrieve it later. Prefer a tag already in the vocabulary from step 1 over minting a near-duplicate: an entry about HTTP written into a store already using `http` is tagged `http`, never `HTTP` or `http-api`. Propose a new tag only where nothing existing fits.

   **Choosing tag forms.** A search term finds a tag when the two are equal, and also when one opens the other, at reduced strength (`http` finds a `https` tag at four fifths; `apple` and `apples` find each other). You therefore do **not** need to carry both a singular and a plural, and should not.

   - **One form per subject, the natural one.** Tag `apple`, not `apple` and `apples`. The extra tag buys nothing and clutters the vocabulary.
   - **Add a second tag only where a form differs by more than its ending.** `route` and `routing` do not find each other, because `route` is not the opening of `routing`. Where both are genuinely likely search words, carry both.
   - **Do not collapse distinct subjects into one tag.** Reuse an existing tag when it means the same thing; an entry about HTTPS is tagged `https` even though `http` is already in the vocabulary, because those are different subjects rather than two spellings of one. The convergence rule exists to stop `HTTP`, `http-api` and `http_api` accumulating beside `http`; it does not license merging `https` into `http`. Prefix matching already relates `http` and `https` at reduced strength, which is the correct relationship between them: related, not identical.

4. Decide (or ask the user) which **store** to write to — a `tier` and a `name` from the enumeration in step 1 — and the entry **body**. Knowledge about one repo's own code belongs in that repo's store, under the name the project registered it by; knowledge that spans repos belongs in one of the project's shared stores. The path comes from the category routing in step 2.
5. Stage the body on disk under `.spektacular/tmp/<slug>.md` using the `Write` tool. Open it with a YAML frontmatter block declaring the tags chosen in step 3, then a blank line, then the body:

   ```markdown
   ---
   tags: [go, http, routing]
   ---

   # HTTP routing standard

   All Go services route HTTP endpoints through chi.
   ```

   Tags travel in the file, not in `--data`, so the write invocation below is unchanged by them. An entry with no tags simply has no block. Do not pipe the body via stdin; the only supported invocation is `--file <staged>`.
6. **Show the user the destination, the proposed tags, and the body before writing.** The destination must state the **tier**, the **store name**, and the **path** — approval is for where the entry lands, not just what it is called — and the **tags** alongside them, since they decide whether the entry is ever found again. This is one gate, not two: tags are confirmed with everything else, not separately. Wait for **explicit confirmation** ("yes", "go ahead", or equivalent). If the user asks for changes, revise the staged body and re-show — never write on an implicit signal.
7. Only after explicit confirmation, run:
   ```
   spektacular knowledge write --data '{"tier":"<tier>","name":"<name>","path":"<category>/<slug>.md"}' --file .spektacular/tmp/<slug>.md
   ```
   A write that leaves out the tier or the store name is refused, and the refusal lists the names available in that tier.
8. Remove the scratch file after a successful write: `rm .spektacular/tmp/<slug>.md`.

# Intent: update

Triggered when the user wants to revise an existing entry.

1. Identify the target entry. Run `spektacular knowledge search <query>` (or read the user-supplied path directly) to locate it. A hit carries its own `tier`, `name` and `path`, which is everything a read needs, so no further disambiguation is required. Confirm the store and path with the user if there is any ambiguity.
2. Read the current body with `spektacular knowledge read --data '{"tier":"<tier>","name":"<name>","path":"<path>"}'`.
3. Apply the user's revision intent to produce new content. Stage the revised body under `.spektacular/tmp/<slug>.md` using the `Write` tool. **Carry the entry's existing frontmatter block through unchanged** unless the revision is itself about the tags: a write replaces the whole file, so dropping the block silently strips the entry's tags and makes it harder to find. If the revision changes what the entry is about, revise the tags with it, following the tag-form rules in the contribute intent.
4. **Show the user the tier, store name, path, tags, and proposed new body (or a diff against the current body) before writing.** Wait for **explicit confirmation**.
5. Only after explicit confirmation, run:
   ```
   spektacular knowledge write --data '{"tier":"<tier>","name":"<name>","path":"<path>"}' --file .spektacular/tmp/<slug>.md
   ```
   The tier, name and path must all match the original — that is what makes this an update rather than a new entry somewhere else.
6. Remove the scratch file after a successful write: `rm .spektacular/tmp/<slug>.md`.

# Intent: audit

Triggered when the user wants the tags on existing entries reviewed — entries written before tags existed, or tagged carelessly. The audit **reads and proposes only**. It composes the primitives the other intents already use and adds no new command, no bulk operation, and no second write path.

1. Enumerate the entries in scope with `spektacular knowledge list`, narrowing with `--tier` and a repeatable `--filter` when the user names particular stores. Load the vocabulary already in use with `spektacular knowledge tags`.
2. Read each entry in scope with `spektacular knowledge read --data '{"tier":"<tier>","name":"<name>","path":"<path>"}'`.
3. For each entry, judge its **current** tags against its content and report two things:
   - **Unsupported tags** — a tag the entry's content does not bear out. Report it for removal.
   - **Missing tags** — a subject the entry is clearly about but carries no tag for. Propose one, preferring a tag already in the vocabulary over a new one.

   Apply the **Choosing tag forms** rules from the contribute intent unchanged — do not restate or reinterpret them here. Two failure modes are specific to auditing, and both matter:

   - **Do not over-merge.** A tag that is a genuinely distinct term from a similar-looking existing tag is never unsupported and never a candidate for merging. An entry tagged `https` must not be told to use `http` instead: those are different subjects, and prefix matching already relates them at reduced strength, which is the correct relationship. The convergence rule exists to stop `HTTP` and `http-api` accumulating beside `http`, not to collapse neighbouring subjects into one.
   - **Do prune what prefix matching already reaches.** A tag made redundant *because* a shorter form opens it — `apples` sitting beside `apple` — should be reported as removable. It buys no retrieval that `apple` does not already provide, and leaving it is how a vocabulary silently doubles.

4. **Propose per entry, and confirm per entry.** Show the user one entry's tier, store name, path, current tags, and the proposed tags with a reason for each addition and removal. Wait for **explicit confirmation for that entry**. Accepting one entry's changes never applies another's, and declining one never carries to the next — each entry is its own decision.
5. Only after explicit confirmation for that entry, stage its revised body under `.spektacular/tmp/<slug>.md` with the `Write` tool, carrying the entry's content through unchanged and altering only its frontmatter block, then write it with the existing command at the entry's **original** tier, name and path:
   ```
   spektacular knowledge write --data '{"tier":"<tier>","name":"<name>","path":"<path>"}' --file .spektacular/tmp/<slug>.md
   ```
6. Remove the scratch file after each successful write: `rm .spektacular/tmp/<slug>.md`. Then move to the next entry.

An audit that reaches `spektacular knowledge write` without passing the per-entry confirmation in step 4 is a bug in the skill's execution, exactly as it would be in the contribute and update intents.

# Intent: maintenance

Triggered when the user wants to know whether the knowledge base is still **true** — not whether it is well labelled, which is the audit intent one section above. Maintenance **reads and proposes only**. It composes the primitives the other intents already use plus `spektacular knowledge delete`, and adds no bulk operation, no recursive operation and no second write path.

1. Enumerate the entries in scope with `spektacular knowledge list`, narrowing with `--tier` and a repeatable `--filter` when the user names particular stores.
2. Read each entry in scope with `spektacular knowledge read --data '{"tier":"<tier>","name":"<name>","path":"<path>"}'`.
3. Classify each entry as exactly one of four verdicts:
   - **current** — the entry still describes how the project works, or states a standard it is meant to meet.
   - **stale** — the entry's subject no longer exists. The file, command, flag, package or behaviour it is about is gone.
   - **incorrect** — the subject still exists but the entry describes it wrongly.
   - **unverifiable** — the entry cannot be checked from the code, for example a claim about intent, process or an external system.

4. **The classification rule that decides whether this review helps or harms.** An entry stating a standard the code has not yet met is **current**, not stale. In this project an entry states the target and the code is what has yet to meet it, so a difference between an entry and the code is work to do, never evidence against the entry. Only an entry whose **subject no longer exists** is stale.

   The failure mode to avoid, concretely: an architecture entry says every store write goes through the CLI, and you find three places writing files directly. That entry is **current** and the code is out of step with it. Proposing its removal would delete the entry doing the most work in the knowledge base. Say the code disagrees with it, and leave the entry alone.

   Likewise, never classify from age or tone. "Looks old", "seems outdated" and "probably superseded" are not findings.

5. **State the evidence for every stale or incorrect verdict.** Name the specific file, command or behaviour that changed, so the user can check the finding rather than take it on trust. A verdict you cannot attach evidence to is **unverifiable**, not stale.
6. **Report drifted category descriptions.** A category's own `README.md` is generated from the project's definition of that category, and one that no longer matches has drifted. Enumerate them with `spektacular knowledge list`, read each with `spektacular knowledge read`, and compare against `spektacular knowledge categories`. Report any mismatch naming the store, the path, and `spektacular init <agent>` as the remedy. The review **reports drift and never repairs it** — bringing a store back into line stays something the user runs deliberately.
7. **Propose per entry, and confirm per entry.** Show the user one entry's tier, store name, path, verdict and the evidence for it, together with what you propose: leave it, correct it, or remove it. Wait for **explicit confirmation for that entry**. Accepting one entry's outcome never applies another's, and declining one never carries to the next — each entry is its own decision.
8. Only after explicit confirmation for that entry:
   - To **correct** it, stage the revised body under `.spektacular/tmp/<slug>.md` with the `Write` tool and write it at the entry's **original** tier, name and path:
     ```
     spektacular knowledge write --data '{"tier":"<tier>","name":"<name>","path":"<path>"}' --file .spektacular/tmp/<slug>.md
     ```
     Remove the scratch file after a successful write: `rm .spektacular/tmp/<slug>.md`.
   - To **remove** it, delete it through the tool and never with your own file tools:
     ```
     spektacular knowledge delete --data '{"tier":"<tier>","name":"<name>","path":"<path>"}'
     ```
9. Move to the next entry.

A maintenance review that reaches `spektacular knowledge write` or `spektacular knowledge delete` without passing the per-entry confirmation in step 7 is a bug in the skill's execution, exactly as it would be in the contribute, update and audit intents.

# Decline handling

If the user declines, asks for changes, or expresses uncertainty at any propose-then-confirm checkpoint, **do not invoke `spektacular knowledge write`**. Either loop back to refine the proposal — adjust the tier, store name, path, or body and re-show — or stop and leave the knowledge store untouched. Removing the staged scratch file at `.spektacular/tmp/<slug>.md` is fine either way; a half-finished proposal should not linger on disk.

In the audit and maintenance intents the same rule applies **per entry**. A decline on one entry stops that entry's change and nothing else: do not carry it forward as a decline of the whole review, and never treat approval of an earlier entry as approval of a later one. Move on to the next entry and propose it on its own merits.

Maintenance is the first intent that can **remove** an entry rather than only rewrite one, so the rule binds harder there. A decline in maintenance means the entry is left exactly as it is — nothing is written and, above all, nothing is deleted. `spektacular knowledge delete` is reached only after explicit agreement for that one entry, and agreement to remove one entry is never agreement to remove another.

The propose-then-confirm contract is enforced by this prose, not by a CLI guard. Treat it as load-bearing: a write without explicit user approval is a bug in the skill's execution, not an acceptable shortcut.
