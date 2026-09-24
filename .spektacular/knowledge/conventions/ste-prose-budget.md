---
tags: [prose, docs, ci]
---

# Keep Markdown within the STE prose budget; only lower it

Markdown is linted with Simplified Technical English (ASD-STE100) by `.github/workflows/ste.yml` against `.ste-budget` (currently 1650). The budget is a ratchet: lower it when prose improves, never raise it to make a PR pass. Run `just ste` locally (part of `just check`).

Source: `.github/workflows/ste.yml` header; `.ste-budget`; `just/utilities.just`.
