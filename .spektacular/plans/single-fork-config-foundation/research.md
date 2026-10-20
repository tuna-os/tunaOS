---
created_date: "2026-10-18"
document_status: final
closed_date: "2026-10-18"
---

# Decisions and evidence

Main at 4a3d4b1 has the build-config seam and flavor resolver. Tests execute
those same entrypoints rather than a new distro table. Desktop manifests and
brand inputs remain sources; phase 1 hashes them but does not resolve package
transactions. The full legacy catalog carries all disabled and admission data.

Both desktop paths need later brand consumers (BRANDING.md). Generated assets
are committed, so generation belongs before build input assembly. PR #3431
proposes related contracts; reconcile them if merged instead of copying them.

The pinned Spektacular 0.20.0 tool reports a version match. Procedural approvals
use AGENTS.md's unattended rule. Maintainer design sign-off remains pending.
