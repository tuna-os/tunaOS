# ADR 0008 — Where shell ends and Python begins

**Status**: Proposed
**Date**: 2026-08-14
**Tracks**: [#1651](https://github.com/tuna-os/tunaOS/issues/1651)

## Context

[#1651](https://github.com/tuna-os/tunaOS/issues/1651) reports Python "mixed
into" a shell-heavy repo with no declared boundary. Measured on 2026-08-14:

| | count |
|---|---|
| `*.sh` | 149 |
| `*.bats` | 95 |
| `*.py` | 33 |
| `*.just` | 6 |

So the ratio is real. What the issue also claims — that this produces a **dual
source of truth**, "the same job implemented in both bash and Python" — did not
survive checking its own three examples:

- **Desktop verify.** `scripts/desktop-verify.py` sends a screenshot to a
  Vision Language Model and asserts desktop state from the reply.
  `build_scripts/checks/verify-desktop-experience.sh` is an in-image contract
  check that emits a marker to `ttyS0`. Different jobs at different times, and
  `iso-e2e.sh` (shell) *calls* the Python one — that is the boundary working,
  not a duplication.
- **Changelog generation.** `.github/changelogs.py` is the only implementation.
  `tests/test_changelogs.py` is its test.
- **Boot gate ownership.** `tests/test_boot_gate_ownership.py` is a *test*
  asserting a property of `scripts/iso-e2e.sh`. A test in another language is
  not a second implementation.

There is no drift risk to fix here, because there is nothing implemented twice.
What is true is that the boundary is **undocumented** — consistent in practice,
discoverable only by reading 182 files.

## Decision

Write down the split the codebase already follows.

**Shell** (`build_scripts/`, `scripts/`, `.just`, workflow `run:` blocks) — the
default. Process orchestration: invoking package managers, podman/buildah, QEMU,
`dnf`/`apt`/`pacman`, moving files, wiring CI steps. Shell is where this project
talks to the system, and rewriting that in Python buys nothing.

**Python** (`scripts/*.py`, `.github/*.py`) — reach for it when the task is
*parsing, generating, or calling an API*, and would be fragile as text
manipulation:

- structured input/output — `gen-matrix-status.py`, `generate-workflows.py`
- HTTP/JSON APIs — `desktop-verify.py` (VLM), `fire-copilot-batch.py`
- anything needing its own unit tests

The signal is not size. It is whether the code would otherwise parse structured
data with `grep`/`sed`/regex.

**Neither**: if a real tool already handles it, use the tool. `yq` is a hard
dependency (`_ensure-deps` fails without it) and parses YAML properly; reaching
for `python3 -c "import re; ..."` to pull a field out of YAML is the one thing
this ADR actually asks people to stop doing. See Consequences.

**Tests follow the language under test.** `bats` for shell, `pytest` for Python.

## Consequences

### Done here

`just/custom-overlay.just` had four inline `python3 -c` regex extractions
pulling `base:`/`tag:` out of `custom/image.yaml`. They are replaced with `yq`.
This is not tidying — the regex was wrong:

```
$ printf '# set tag: WRONG-VALUE here\ntag: correct-tag\n' > t.yaml
regex picks: WRONG-VALUE
yq picks:    correct-tag
```

`re.search(r'tag:\s*(\S+)')` matched the first line containing `tag:` anywhere,
including inside a comment. Worse, `.group(1)` on a `None` raised
`AttributeError` straight into `2>/dev/null || echo <default>`, so a malformed
or missing field silently produced the default image tag. A wrong image built
without complaint is worse than a build that fails.

The remaining inline `python3 -c` in `just/utilities.just` is
`python3 -c "import pytest"` — an availability probe, not logic. It stays.

### Deliberately not done

**"Move `tests/` to a single harness"** (#1651's recommendation) is rejected.
The split is not accidental: `bats` runs shell in a shell, `pytest` imports
Python modules. Merging them means driving one language's code through the
other's runner — losing `run`/`status` for shell tests, or losing imports,
fixtures and assertion rewriting for Python ones. The current suites are already
unified where it counts: `just test` runs both, and CI fails on either.

**Rewriting Python into shell, or shell into Python, to reduce the file count.**
There is no duplication to consolidate, and 33 files is not a maintenance
problem — an undocumented rule was.

### Cost

A rule nobody enforces drifts. `tests/bats/test_language_boundary.bats` asserts
the one mechanical part: no new `python3 -c` inline regex parsing of YAML in
`just/` modules. The rest of this ADR is judgement and is reviewed, not tested —
a test that tried to decide "should this have been Python?" would be wrong more
often than the humans.
