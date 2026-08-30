# Architectural Standards: Python Script Organization, Language Boundaries, & Pytest Test Harness Policy

**Status**: APPROVED (Active Architectural Policy)  
**Tracks**: [#1651](https://github.com/tuna-os/tunaOS/issues/1651) (Python files mixed into shell-heavy repo — linting/test harness policy), [ADR 0008](../adr/0008-shell-python-boundary.md)  
**Owner**: Architecture / Scanner  
**Applies to**: `scripts/`, `.github/`, `just/`, and `tests/`  

---

## 1. Executive Summary

TunaOS contains a polyglot codebase featuring bash scripts, Justfile automation, bats test suites, and Python scripts across orchestration, verification, release generation, and test suites.

Historically, the lack of a documented language boundary and script organization policy led to:
- Confusion regarding when to write a task in shell vs. Python vs. a compiled utility.
- Fragile `python3 -c "import re; ..."` inline snippets embedded within Justfiles and shell scripts.
- Unstructured test organization across pytest and custom scripts.

This document formalizes the architectural boundary between Shell and Python, codifies organization standards for Python modules, and defines the unified Pytest harness architecture.

---

## 2. Language Boundary & Decision Framework

The codebase follows the clear division established in [ADR 0008](../adr/0008-shell-python-boundary.md):

```
                        ┌──────────────────────────────────────────┐
                        │              Task Trigger                │
                        └─────────────────────┬────────────────────┘
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    ▼                                                   ▼
       Process / System Orchestration                       Structured Logic / APIs
  ┌───────────────────────────────────────┐               ┌───────────────────────────────────────┐
  │ - Invoking package managers (dnf/apt) │               │ - Parsing/generating JSON, YAML, SPDX │
  │ - Container operations (podman/buildah│               │ - Consuming REST / GraphQL APIs       │
  │ - Direct QEMU / KVM process spawning  │               │ - Complex matrix state computation    │
  │ - Linear CI pipeline steps            │               │ - Vision Language Model verification  │
  └───────────────────┬───────────────────┘               └───────────────────┬───────────────────┘
                      │                                                       │
                      ▼                                                       ▼
            ┌───────────────────┐                                   ┌───────────────────┐
            │    Bash Script    │                                   │   Python Module   │
            │ (`scripts/*.sh`)  │                                   │ (`scripts/*.py`)  │
            └───────────────────┘                                   └───────────────────┘
```

### 2.1 When to Use Shell (`bash`)
- **Default for Systems Automation**: Use shell for process invocation, filesystem plumbing, container builds (`buildah`, `podman`), virtualization setups (`qemu`), package management (`dnf`, `rpm-ostree`), and linear CI runner steps.
- **Invariants**:
  - Must include `set -euo pipefail`.
  - Must pass `shellcheck` static analysis.
  - Avoid text-based parsing of structured formats (`grep`/`sed` parsing of JSON/YAML).

### 2.2 When to Use Python (`python3`)
- **Structured Data Processing**: Generating or transforming YAML, JSON, SPDX SBOMs, Markdown tables, or package metadata matrices (e.g. `gen-matrix-status.py`, `packages_to_spdx.py`).
- **External Web & AI APIs**: Interfacing with GitHub APIs, Copilot/LLM services, or Vision Language Models (e.g. `desktop-verify.py`, `installer-walkthrough.py`).
- **Complex Algorithmic Logic**: State machines, workflow matrix synthesis (`generate-workflows.py`), and multi-branch decision trees.
- **Unit-Tested Logic**: Any utility logic that requires unit tests with mocks, fixtures, and parameterized edge cases.

### 2.3 When to Use Dedicated CLI Utilities (`yq`, `jq`)
- Querying or mutating specific fields in YAML or JSON files inside shell scripts or `Justfile` recipes must use `yq` or `jq`.
- **Prohibition**: Multi-line or regular-expression `python3 -c "..."` parsing embedded inside `.just` recipes or shell scripts is strictly prohibited.

---

## 3. Python Script Organization & Code Standards

### 3.1 Directory Contract

| Path | Purpose | Standards |
|---|---|---|
| `scripts/*.py` | Repository tooling, verification utilities, generators | Standalone CLI entrypoints; `argparse` documentation; typed. |
| `.github/*.py` | GitHub Actions workflow assistants, changelog scripts | Minimal external dependencies; uses `GITHUB_*` environment. |
| `tests/` | Pytest test suite modules (`test_*.py`) | Pytest fixtures; assertions; hermetic mocks. |
| `tests/python/` / `tests/pytest/` | Sub-suite test helpers and shared test harnesses | Reusable test utilities and mock definitions. |

### 3.2 Code Quality Standards
Every production Python script in the repository must adhere to:

1. **Python Version**: Compatible with Python 3.11+.
2. **Standard Entry Point**:
   ```python
   #!/usr/bin/env python3
   """Module docstring explaining script purpose and usage."""

   import argparse
   import sys

   def parse_args() -> argparse.Namespace:
       parser = argparse.ArgumentParser(description=__doc__)
       parser.add_argument("--target", required=True, help="Target image or path")
       return parser.parse_args()

   def main() -> int:
       args = parse_args()
       # execution logic
       return 0

   if __name__ == "__main__":
       sys.exit(main())
   ```
3. **Type Annotations**: All public functions, helper methods, and return values must include type annotations (`typing` / built-in generics).
4. **Dependency Minimization**: Favor Python standard library (`urllib.request`, `json`, `argparse`, `dataclasses`, `pathlib`) over third-party packages for operational scripts unless complex capabilities (e.g., `pytest`, `requests`, `pyyaml`) are required.

---

## 4. Pytest Test Harness Policy

### 4.1 Test Suite Organization & Language Coexistence
TunaOS maintains separate, specialized harnesses for different testing domains per [ADR 0008](../adr/0008-shell-python-boundary.md):
- **`tests/bats/*.bats`**: BATS runs shell in a subshell for direct CLI output, process exit code, and filesystem testing.
- **`tests/test_*.py`**: Pytest runs Python tests, leveraging module imports, fixtures, assertion rewriting, and mocks.

### 4.2 Pytest Conventions
1. **Naming Conventions**:
   - Test files: `tests/test_<subject>.py`
   - Test functions: `def test_<behavior>_<condition>():`
   - Test classes (when grouping related tests): `class Test<Subject>:`
2. **Hermetic Isolation**:
   - Tests must run independently and must not depend on network access or mutated ambient state unless explicitly marked with `@pytest.mark.integration` or `@pytest.mark.e2e`.
   - Use `unittest.mock.patch` or `pytest-mock` to mock external API requests and subprocess calls.
3. **Parameterized Testing**:
   - Use `@pytest.mark.parametrize` for testing matrices of image flavors, versions, and configurations.

### 4.3 Unified Execution
Developers and CI execute the suites through unified `just` recipes:
- `just test-python`: Executes the pytest suite (`pytest tests/`).
- `just test-bats`: Executes the shell BATS suite.
- `just test`: Orchestrates both suites, failing if either returns a non-zero exit code.
