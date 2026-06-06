# Agent Guidelines for TunaOS

> The authoritative agent guide lives at [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md). Read that file for complete instructions on setup, building, pre-commit workflow, architecture, and troubleshooting.

> **Claude Code / Gemini CLI users:** Configure your tool to read this file via `--custom-instructions AGENTS.md` or equivalent.

## Quick Reference

```bash
just fix && just check   # format + validate (mandatory before every commit)
just yellowfin base      # build a single variant (fastest test)
just --list              # show all available commands
```
