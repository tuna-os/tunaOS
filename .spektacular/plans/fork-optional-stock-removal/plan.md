# Optional stock package removal

## Scope and approval

Continue the user's single-config customization request with exact `fastfetch`
removal on direct Grouper and Yellowfin GNOME builds. No new layering schema,
stock defaults, release gates, or automatic pruning. Every other removal remains
an explicit unsupported error. No merge is authorized.

The Spektacular executable is unavailable in this environment. This manual plan
records the bounded implementation and autonomous review checkpoints, following
RFC 011's repository conventions.

## Implementation

- Share source-controlled eligibility between preview and native adapter.
- Capture stock desktop inventory before fork additions; retain its digest in
  the calling shell, not solely in a file that later package scripts can rewrite.
- Finish removals after desktop setup and branding, using a fresh strict desktop
  contract, native dependency preflight, exact inventory delta and postcontract.
- Complete the overall package receipt only after every check succeeds.
- Collect partial contract-derived package-owner evidence separately, without
  treating incomplete evidence as a removal authorization policy.
- Prove actual fastfetch packages in disposable containers from real GNOME
  canary images. Fixture tests alone do not establish full-image support.

## Verification

Focused shell/compiler/helper regression tests, full fork suite, mandatory
`just fix && just check`, independent safety review, native family CI and actual
image canary evidence. Publish a separate draft stacked on the protected-inventory
PR and track checks to terminal. Do not change the held description of PR #3449.

## Native build proof dependency integration

The separate native build matrix needs the existing canary base/desktop fixes
and current source-routing compiler. Integrate the reviewed canary snapshot
`f05875a1` (local `7b29cedc`) as an explicit dependency of PR #3453. Preserve
its attribution and leave PR #3445 unchanged. The temporary review diff includes
that dependency until the upstream bases converge.

For each admitted variant, build a package-only stock context, run the guarded
disposable child proof, then build an actual `remove: [fastfetch]` context.
Verify final native inventory and completed contract receipts. Keep existing
no-cache settings, read-only repository permissions and no registry publication.
Do not infer boot, installer or identity qualification from these package tests.
