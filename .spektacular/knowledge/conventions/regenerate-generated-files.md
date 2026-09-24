---
tags: [generated, workflows, docs]
---

# Regenerate generated files; never hand-edit them

Never hand-edit generated output. `.github/workflows/build-*.yml` come from `scripts/generate-workflows.py` (`just generate-workflows`); `MATRIX-STATUS.md`, the README matrix and `matrix-provenance.json` come from scripts. Edit the source (`.github/build-config.yml`, the generator) and regenerate. `just check` fails with "Generated workflow files are stale" on drift.

Status tables are derived by a script, never transcribed (AGENTS.md PR contract rule 3).

Source: `just/utilities.just` (check recipe), `AGENTS.md` rule 3.
