# tunaOS Package Sourcing Policy

**Status**: ACTIVE — adopted 2026-08-11; migration of existing exceptions is tracked below
**Owner**: tuna-os (hanthor) / strategist
**Tracks**: [#1319](https://github.com/tuna-os/tunaos/issues/1319) (maintainer directive), [#1323](https://github.com/tuna-os/tunaos/issues/1323) (strategic framing)
**Interacts with**: Q4 supply-chain hardening ([#1193](https://github.com/tuna-os/tunaos/issues/1193), [#1187](https://github.com/tuna-os/tunaos/issues/1187)), upstream snapshot automation ([#1194](https://github.com/tuna-os/tunaos/issues/1194)), desktop parity ([#1294](https://github.com/tuna-os/tunaos/issues/1294))

---

## Purpose

Define where tunaOS packages come from. The maintainer directive
[#1319](https://github.com/tuna-os/tunaos/issues/1319) is explicit: **default to
system repos / tideforge — not PPAs, COPRs, OBS, or AUR**. Packages missing from
the base image's system repos should be built in-house; a small allowlist of
trusted third-party repos (maintainer cites the codec/Nvidia repos) is
acceptable where building in-house is not yet viable.

This policy operationalizes that directive into a written, reviewable sourcing
contract so every variant's `apt:` / `dnf:` / `zypper:` / `pacman:` / `emerge:`
manifest block has a clear governing rule — and so the Q4 supply-chain goals can
attest *what* is actually being signed and pinned.

## Sourcing tiers (preference order)

| Tier | Source | Use when |
|------|--------|----------|
| 1 | **Base system repos** (Fedora/AlmaLinux/Debian/Ubuntu/openSUSE/Arch/Gentoo defaults) | Package exists, version acceptable, no fork needed |
| 2 | **Tideforge** (in-org build service, [tideforge.org](https://tideforge.org)) | Package missing from base repos or needs tunaOS patches; build from source in-house |
| 3 | **Trusted third-party allowlist** | Genuine gap that in-house building cannot yet cover (e.g. codecs, Nvidia); see admission process below |
| ✗ | **PPAs / COPRs / OBS / AUR and other ad-hoc repos** | **Not allowed** — no exception without an allowlist entry |

## Rules

1. **System-repos-first default** — a manifest must use base system repos
   whenever the package is available there at an acceptable version. Adding a
   tier-2/tier-3 source requires a comment in the manifest citing the gap and
   the governing tracker.
2. **Build-in-house over consume-third-party** — missing packages go to
   Tideforge (or an in-org builder) before any external repo is considered.
   This generalizes the Q2 COPR-elimination win ([#436](https://github.com/tuna-os/tunaos/issues/436)) org-wide.
3. **Allowlist is narrow and reviewed** — the third-party allowlist exists for
   gaps, not convenience. Every entry needs a written justification and a
   review date; see admission process below.
4. **No silent drift** — adding a new external repo to a manifest without an
   allowlist entry is a policy violation and blocks CI/release (enforcement
   path TBD — see §Enforcement below).
5. **Variant exceptions are documented** — an exception applies to a *specific*
   variant+desktop cell, is recorded in that variant's manifest comment or
   [ROADMAP.md](./ROADMAP.md) row, and is re-evaluated at the next quarterly
   checkpoint. Non-RPM bases (sailfin/flounder/grouper/marlin/guppy) are the
   expected home of exceptions during the desktop-parity transition ([#1294](https://github.com/tuna-os/tunaos/issues/1294)).

## Third-party allowlist admission

A repo enters the allowlist only when all of the following hold:

- **Ownership & maintenance**: an identifiable owner/maintainer with a public
  issue tracker and a release process; not a single-commit/abandoned project.
- **Provenance & signing**: packages are reproducibly built or at least
  checksum/signature-verifiable at install time; prefer repos that publish
  signatures.
- **Scope**: the repo supplies exactly the gap (e.g. codecs, Nvidia drivers) —
  not a general-purpose mirror of packages available in tier 1/2.
- **History**: no known supply-chain incidents; activity within the last 6
  months.
- **Documentation**: the entry is recorded in this document's allowlist table
  with a justification, the consuming variants, and a next review date.

### Allowlist (current)

| Repo | Gap covered | Consuming variants | Added | Next review | Justification |
|------|-------------|--------------------|-------|-------------|---------------|
| *(pending audit)* | — | — | — | — | Audit per variant lands before entries are added; maintainer-cited codec/Nvidia repos are the starting candidates |

## Audit & transition plan

1. **Audit (Q3 checkpoint 2026-08-22, [#1323](https://github.com/tuna-os/tunaos/issues/1323))**: inventory every manifest's external
   `apt:`/`dnf:`/`zypper:`/`pacman:`/`emerge:` source across all published
   variants; classify each as tier 1/2/3 or violation; publish the table.
2. **Migrate (Q3–Q4)**: move tier-3/✗ sources that have in-house equivalents
   to Tideforge; drive the 14-recipe COSMIC build-out already tracked in
   [ROADMAP.md](./ROADMAP.md) ([#964](https://github.com/tuna-os/tunaos/issues/964) COSMIC-off-PPA is the flagship migration).
3. **Attest (Q4)**: fold the final source inventory into the supply-chain
   attestation work ([#1187](https://github.com/tuna-os/tunaos/issues/1187)) so SBOMs and signing cover the *actual* source graph.

## Enforcement

- **Checkpoint gate**: the 2026-08-22 Q3 checkpoint ([#1299](https://github.com/tuna-os/tunaos/issues/1299)) reviews the audit table; policy
  violations are surfaced there.
- **CI**: `scripts/check-package-sources.py` blocks new manifest changes that
  add COPR, PPA, OBS, AUR, or an unapproved repository URL. Existing legacy
  declarations remain migration inventory until their package is available in
  Tideforge or a documented allowlist exception is approved.

---

*Drafted by the strategist agent (ACMM L6 — full mode). Review requested from
maintainer (hanthor) and sec-check before promotion from DRAFT.*
