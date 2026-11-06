---
created_date: "2026-10-20"
document_status: draft
---

# Research: 20261020031206-primary-tunaos-toml-configuration

## Alternatives considered and rejected

- Rename optional fork intent: RFC013 and resolve-fork-config.py leave stock catalogs authoritative. This does not meet the maintainer's correction.
- Commit a generated matrix and rely on Renovate regeneration: renovate.json edits the YAML directly; hosted postUpgradeTasks is unverified, and Just Fix's PR checkout/push is not a reliable retrigger path. Routine dependency bumps must not become red.
- Rewrite all package and build engines now: hides default-output changes and exceeds the bounded first migration.

## Chosen approach — evidence

Root tunaos.toml owns the full matrix. Generate an ignored compatibility adapter at checkout/setup, before every reader. Shell callers use scripts/lib/build-config.sh; Python callers share the core. Workflow inline reads require explicit setup. Renovate edits only TOML. The read-only prototype proves 14-variant/155-flavor/15-desktop data can round-trip without loss, but only matrix ownership moves first.


The direct workflow inventory requires preparation beyond setup-yq: build-flavor, desktop-contract-sweep, reusable-build-image build_push and manifest, matrix-status, and weekly-boot-report. Wolfi installs yq independently and needs Python explicitly. Its retry regression hardcodes the dependency list and must include python3. .github/runs-on.yml selects Ubuntu24 images, so the current custom-runner paths share the hosted baseline. Tests cover fallback selection using a shim and actual Python 3.10.22 with the pinned tomli 2.2.1 parser.

## Files examined

- tunaos:scripts/lib/build-config.sh:1 — existing overrideable shell seam.
- tunaos:renovate.json:82 — matrix base-image regex directly writes YAML today.
- tunaos:.github/workflows/just-fix.yml:38 — no verified regenerate-and-retest bot path.
- tunaos:scripts/resolve-fork-config.py:70 — source receipt must include primary TOML, not an untracked derivative.
- tunaos:scripts/generate-workflows.py:6 — direct legacy matrix reader.
- tunaos:just/utilities.just:62 — mandatory local checks and generated workflow drift.
- tunaos:.github/workflows/test.yml:82 — ubuntu-latest with no Python version pin.

## External references

- projectbluefin/utah packages/utah.toml and scripts/install-packages.py — readable grouped lists, deterministic ordered resolution, exact installed contract shared with verifier.
- projectbluefin/utah scripts/verify-rpm-contract.py — version and origin constraints must be consumed, not accepted as inert fields.
- PyPI tomli 2.2.1 metadata — Python >=3.8, pure wheel SHA256 cb55c73c5f4408779d0cf3eef9f762b9c9f147a77de7b258bef0a5628adc85cc. Common TOML 1.0 with tomllib. Both parsers agree on full local prototype.

## Prior plans / specs consulted

RFC013 and the foundation/consumer specifications: reuse validators/equivalence tests, supersede separate stock-versus-fork ownership. No external design references are registered for the new spec.

## Open assumptions

Native Python 3.10.22 execution passed 65 core tests with tomli 2.2.1; the same 65 passed on Python 3.12 with tomllib. This evidence is separate from full integration and artifact qualification. Consumer inventory must cover container-copy and test-fixture contexts before deleting tracked adapter. No automatic package mapping or full transaction parity is claimed.

## Drafting assumptions

### Staged execution boundary (phases)
- **Decision**: Plan all four milestones; implement only the approved matrix milestone now.
- **Rationale**: The first implementation is a bounded ownership migration while the complete requirement includes packages, branding and authoring tools.
- **Rejected**: Claiming matrix parity completes the product goal; rewriting all mechanisms in one change.

### Procedural self-confirmations (phases)
- **Decision**: The agent supplies procedural review confirmations under AGENTS.md “No person present.”
- **Rationale**: A person is not present in this workflow; the repository explicitly authorizes this procedure.
- **Rejected**: Attributing the confirmation to a human, treating it as RFC acceptance, or broadening implementation permission.

### Editor and native query evaluation (phases)
- **Decision**: Evaluate comment-preserving tomlkit and reuse current native query helpers, with explicit parity gates before selection is considered complete.
- **Rationale**: One validated schema must serve both hand and tool edits; package-name resolution requires measured context.
- **Rejected**: A second CLI schema, string-similarity package guesses, or silent partial edits.

### Retain existing feature namespace (assemble)
- **Decision**: Keep 20261020031206-primary-tunaos-toml-configuration.
- **Rationale**: The workflow and matching spec already use this namespace; the generic sequential-number example is not a reason to rename a resumed artifact.
- **Rejected**: Creating a second numbered plan for the same approved scope. Agent self-confirmation follows the no-person rule.

## Rehydration cues

Read docs/PRIMARY-CONFIG-MIGRATION.md and the current spec. Re-run the matrix prototype outside production paths. Refresh main and run all mandatory tests before publication. Existing PR3445 qualification is frozen and untouched.
