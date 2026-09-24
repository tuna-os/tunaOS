---
tags: [adr, shell, python, yaml]
---

# ADR 0008: where shell ends and Python begins

Proposed (followed in practice). Shell for orchestration; Python for parsing/generating/API calls; `yq` for YAML, never inline Python regex (the regex version silently picked values from comments). Rejected a single test harness and language rewrites. `docs/adr/0008-shell-python-boundary.md`.
