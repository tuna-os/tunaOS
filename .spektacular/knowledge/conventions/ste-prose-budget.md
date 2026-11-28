---
tags: [prose, docs, ci]
---

# Keep Markdown within the STE prose budget; only lower it

`.github/workflows/ste.yml` lints Markdown with Simplified Technical English (ASD-STE100) against the number in `.ste-budget`. The budget is a ratchet: lower it when prose improves, never raise it to make a PR pass. A manual (`workflow_dispatch`) run of `ste.yml` fails when the count is below the budget, and gives the new number to write. Run `just ste` locally (part of `just check`).

Source: `.github/workflows/ste.yml` header; `.ste-budget`; `just/utilities.just`.
