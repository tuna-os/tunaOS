# Fork boot and installer projections

Continue RFC 013 and ADR 0012 on the identity staging slice (#3440). No merge,
release, hold change or live-root write is approved by this plan.

1. Generate a PNG lettermark and a one-frame version of the shipped Plymouth
   script. Keep password, question and normal-display callbacks.
2. Use the existing early theme selector before dracut. Refuse a failed fork
   selection; preserve the stock fallback when no fork manifest exists.
3. Generate the common installer branding.json from resolved identity and URL
   fields. Recipes and matching catalog leaves are generated adapters. Preserve
   image references, IDs, install options and unrelated catalog entries.
4. Extend installed receipts and read-only runtime verification. Keep the build
   and mutating live-root gates until installer and boot artifacts are tested.
5. Run focused and aggregate checks, independent review, then open a stacked
   draft and check exact-head CI. Do not claim a source test qualifies an image.

The Spektacular CLI is absent (`command -v spektacular` returns no path).
This manual plan continues the existing approved architecture. Procedural plan
confirmation is self-approved under AGENTS.md; product rollout is not approved.
