---
tags: [yaml, shell, python]
---

# Parse YAML with `yq`, never with inline Python regex

Shell is the default for orchestration; Python is for parsing, generating, or calling APIs. Never pull a field out of YAML with `python3 -c "import re..."` or `grep`/`sed`; use `yq` (a hard dependency). Tests follow the language under test: bats for shell, pytest for Python.

Source: ADR 0008 (`docs/adr/0008-shell-python-boundary.md`); enforced for `just/` by `tests/bats/test_language_boundary.bats`.
