# ADR 0010: Spec-driven work with Spektacular

- Status: accepted
- Date: 2026-09-24
- Issue: [#2673](https://github.com/tuna-os/tunaOS/issues/2673)
- RFC: [RFC 011](../rfc/rfc011-spektacular.md)

## Context

Agents open most tunaOS pull requests. The intent of a change sits in an
issue or a chat. A reviewer sees the design for the first time in the diff.
The lessons in `docs/ci-troubleshooting.md` and `docs/adr/` reach an
agent only if it knows to look. A prototype on #1893 (PR #2682) tested
Spektacular 0.20.0 on a real port between branches.

## Decision

Use Spektacular for the changes that the table in `AGENTS.md` names. An RFC
must use it. We recommend it for a change that touches more than one area
or ports work between branches. Small fixes do not use it.

The project commits `.spektacular/` (config, knowledge base, specs, plans,
changelogs) and the `spek-*` skills in `.claude/skills/`. `image-versions.yaml`
pins its version as `spektacular`.

## Consequences

- Each plan loads the conventions and the glossary from
  `.spektacular/knowledge/`. A stale entry misleads every later plan, so
  each entry cites the file it comes from.
- The workflows are long. For a change of about 50 lines, the prototype
  wrote about 390 lines of plan.
- Some steps expect Go tooling and a person at the keyboard. `AGENTS.md`
  tells agents what to do instead, until upstream fixes them.
- No build, image or CI job depends on Spektacular. To revert, remove
  `.spektacular/`, the `spek-*` skills and the section in `AGENTS.md`.
