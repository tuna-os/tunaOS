# Typed APT repositories

Continue RFC013 with a backward-compatible explicit APT source type. Require
suites/components and a downloaded key digest. Stage source-specific keyrings,
preflight all collisions and reject symlinks. Preserve signature verification.
Do not invent Portage overlay or Arch database semantics from RPM fields.

Use scoped fork-only refresh/install guards to stop forced recovery and retry
after refresh or solver failure. Retain stock behavior outside the adapter.
Run schema, staging, collision, key failure and actual wrapper dispatch tests.
Keep native signed-repository and image acceptance gaps explicit in a draft PR.
Procedural steps self-approved under AGENTS.md; no merge approval is implied.
