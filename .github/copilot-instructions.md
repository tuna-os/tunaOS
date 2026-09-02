# TunaOS — instructions for Copilot

The agent instructions for this repository live in [`AGENTS.md`](../AGENTS.md)
and the authoritative guide it points to,
[`docs/AGENT_GUIDE.md`](../docs/AGENT_GUIDE.md). Read those first.

This file used to carry its own copy of the variant table, the flavor chain
and the build commands, and it drifted: it still described the pre-July-2026
`base → dx → nvidia` flavor chain and `just yellowfin base` a month after the
manifest-driven refactor replaced both. One instruction set, referenced from
every tool's entry point (`CLAUDE.md`, `.cursor/rules`, this file), cannot
drift.

The one thing worth repeating here because Copilot reads this file first:

```bash
just fix && just check   # mandatory before every commit
just ci                  # what the PR gate runs, locally
```
