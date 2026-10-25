# Name/logo consumer staging

RFC013 phase2 continuation, stacked on the local consumer preview. This is draft
implementation, not maintainer approval of runtime rollout. No merge requested.

1. Read RFC013, ADR0012, agent guide, both desktop paths and brand contracts.
2. Audit installer frontend source and Flatpak host-path semantics.
3. Materialize exact name/logo assets from the same pinned config, with source
   and input/output receipts. Restrict unsupported desktop routes explicitly.
4. Exercise os-release, GNOME asset paths, console and fastfetch in a disposable
   root through an idempotent real-format consumer. Preserve stock behavior.
5. Block live-root and image-build use while installer/Plymouth remain incomplete.
6. Run focused/aggregate checks, open a stacked draft and monitor exact-head CI.

Spektacular v0.20.0 CLI is unavailable in this environment; the version check
was attempted. This records the plan manually rather than inventing tool output.
Procedural standalone plan confirmation is self-approved per AGENTS.md; no
product approval or merge authority is inferred. Runtime canaries remain open.
