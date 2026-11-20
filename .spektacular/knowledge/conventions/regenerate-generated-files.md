---
tags: [generated, workflows, docs]
---

# Regenerate generated files; never hand-edit them

Never hand-edit generated output. `.github/workflows/build-*.yml` come from `scripts/generate-workflows.py` (`just generate-workflows`); `MATRIX-STATUS.md`, the README matrix and `matrix-provenance.json` come from scripts. Edit the source (`tunaos.toml`, or the generator) and regenerate. `.github/build-config.yml` is also generated: `python3 scripts/config.py generate` writes it from `tunaos.toml`, and Git ignores it. `just check` fails with "Generated workflow files are stale" on drift.

Status tables are derived by a script, never transcribed (AGENTS.md PR contract rule 3).

Source: `just/utilities.just` (check recipe), `AGENTS.md` rule 3, `docs/ROLL_YOUR_OWN.md` (step 2), `.gitignore`.
