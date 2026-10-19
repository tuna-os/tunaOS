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
