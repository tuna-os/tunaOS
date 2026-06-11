# Agent Guidelines for TunaOS

> The authoritative agent guide lives at [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md). Read that file for complete instructions on setup, building, pre-commit workflow, architecture, and troubleshooting.

## Quick Reference

```bash
just fix && just check   # format + validate (mandatory before every commit)
just yellowfin base      # build a single variant (fastest test)
just --list              # show all available commands
```

## Agent skills

### Issue tracker

GitHub Issues for `tuna-os/tunaos`, operated via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Defaults — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
