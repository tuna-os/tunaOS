---
created_date: "2026-10-20"
document_status: draft
---

# Primary TunaOS TOML configuration

## Overview

TunaOS and its customizations use one editable TOML configuration for variants,
packages and branding. The same settings drive desktop images and shared
installer presentation. Small authoring tools help people find native packages
and inspect effective settings across bases while preserving hand editing.

## Requirements

- TunaOS's own defaults are authoritative in the primary file, using the same
  schema and consumers as customized values.
- Users can select supported variants, desktops, platforms and image names.
- Users can edit shared and scoped native packages, build-only packages,
  exclusions, repository policy and version requirements in readable sections.
- Users can change names, URLs, logos, emoji and wallpapers in one place.
- Every installer frontend consumes the same shared branding definition.
- Generated machine formats are explicit derivatives and reject drift.
- Invalid, unknown or unsupported configuration fails before build mutation.
- Users can inspect effective configuration and the source of each value.
- Package searches report base/version/architecture/repository context and
  distinguish metadata availability from full transaction resolution.
- A request such as `add htop` resolves the right native packages across the
  configured supported bases and updates the file correctly and idempotently.
  Unavailable or ambiguous results block the edit with actionable evidence.
- Editing tools preserve comments, show proposed diffs and use the same
  validation and resolution rules as builds. Hand editing remains supported.

## Constraints

- Preserve package ordering, native family semantics and current admission
  holds. Configuration does not waive signing or qualification requirements.
- Do not introduce executable configuration or automatic dependency downloads.
- Preserve Python 3.10 authoring support with an explicit tested parser pin;
  target images do not require a TOML parser to consume generated adapters.
- Assets can remain separate referenced files with strict path validation.
- Existing frozen qualification evidence remains bound to its original source.

## Acceptance Criteria

- The default file reproduces all existing matrix values, variant/flavor order,
  aliases, rollout records, platform restrictions and ISO groups.
- Every package and repository operation consumed by a supported build is
  derived from the primary configuration, with no separate stock-only source.
- Installers and verifiers use the same resolved package contract.
- Default identity, wallpaper and installer assets remain equivalent through
  migration; edited values reach all intended consumers and final writers.
- Unknown sections, duplicate keys, bad types/selectors and unsafe asset paths
  fail validation before mutation. Generated-file edits fail drift checks.
- Both supported TOML parsers agree on valid inputs and reject invalid inputs.
- Authoring edits preserve comments and unrelated values and produce a reviewable
  diff. Search results state evidence and do not assert untested solvability.
- Representative built images and real installations pass their existing gates
  before full delivery is claimed. Source parity alone is not qualification.

## Technical Approach

- Use the readable grouped package-contract style from Utah's TOML, extended
  to TunaOS's native package families and shared branding requirements.
- Keep one parser, schema and resolver shared by builds and authoring tools.
- Use generated adapters to migrate existing consumers without a build rewrite.
- Transfer source ownership in reviewed stages; matrix-only migration is not
  completion while package or branding defaults remain outside the file.

## Success Metrics

- One authoritative editable product configuration for TunaOS and customizers.
- No supported field that is accepted but ignored by its consumer.
- No differences in default build inputs at a source-ownership migration.
- Reproducible generated output and actionable field-specific errors.

## Non-Goals

- No change to supported hardware, desktop versions or admission policy.
- No package-name mapping guessed across distributions; generic user intent
  requires measured native matches or verified explicit mappings.
- No automatic publication, credential management or host package installation
  as a side effect of editing or searching configuration.
- No claim that the legacy customization preview completes this interface.

## Verification

Compare complete matrix and desktop-profile data before and after translation.
Exercise package resolution and final branding writers, including overrides.
Run negative schema tests, parser parity, drift and mutation tests. Run the
repository's mandatory formatting, validation and regression gates. Distinguish
source checks, built-artifact checks and real boot/install evidence in reports.
