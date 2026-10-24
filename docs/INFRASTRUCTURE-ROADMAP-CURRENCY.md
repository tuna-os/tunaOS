# Infrastructure roadmap currency

Strategist coordinates a review of tacklebox, corral, remora, iso-builder and
bluefin-cli at the start of every quarter (January, April, July, October).
Repository maintainers own roadmap content and release decisions. Carry unmet
Q3 gates into Q4 with an owner, source issue and next review date; a passed
calendar date does not complete a gate.

Run `python3 scripts/infrastructure-roadmap-currency.py` with `gh` authenticated
(`GH_TOKEN` in automation). The weekly **Infrastructure roadmap currency** workflow
publishes the generated report as a run artifact and job summary. It can also be
run manually. API errors fail the run rather than reporting a missing repository
as healthy. The report uses each repository's default branch and latest commit
touching root `ROADMAP.md`; an edit this quarter is only a review prompt, never
proof that the document's claims are current. Do not copy its live status into a
hand-maintained table.

For each quarterly review:

1. Read the source roadmap and compare readiness claims with immutable releases,
   checksums and linked test/build evidence. Record the evidence in the source
   tracker; remove or qualify claims that lack it.
2. Refresh tacklebox's first versioned release gate and corral's product-release
   discoverability gate before calling their downstream prerequisites satisfied.
   Check [tacklebox#237](https://github.com/tuna-os/tacklebox/issues/237) and
   [corral#210](https://github.com/tuna-os/corral/issues/210) against current
   releases; closure alone does not establish readiness.
3. Review [remora#56](https://github.com/tuna-os/remora/issues/56),
   [iso-builder#229](https://github.com/tuna-os/iso-builder/issues/229) and
   [bluefin-cli#295](https://github.com/tuna-os/bluefin-cli/issues/295) for the
   support-tier, signing and distribution-token dependencies identified in #3230.
   Verify their current state before carrying them forward.
4. For any unresolved roadmap P0 at least seven days old, leave one decision
   escalation in its source issue naming the maintainer role, downstream impact,
   evidence needed, and a proposed next review date. Link it from the quarterly
   planning tracker. Reuse an existing escalation rather than posting weekly
   duplicates. Credentials, signing and publication remain maintainer actions.

The automated P0 list conservatively uses issue creation time and the exact
`P0` label (case insensitive). It includes non-roadmap candidates for review and
cannot discover unlabelled blockers or P0 prose in documents. Review those
manually, including the release gates above. A closed issue is omitted, but its
release claim still needs verification. The report sends no messages and changes
no source repository. Companion roadmap refreshes belong in their repositories;
this procedure establishes central visibility without asserting they have landed.
