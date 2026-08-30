# Issue Completion Verification & Validation Policy

**Status**: Published Policy  
**Tracks**: [#1681](https://github.com/tuna-os/tunaos/issues/1681) (Issue-completion verification gap & validation standards)  
**Applies to**: `tuna-os/tunaos` and all active repositories in the `tuna-os` organization.

---

## 🎯 1. Purpose & Motivation

In a high-velocity development environment leveraging both human contributors and automated agent workflows, the issue lifecycle must maintain strict alignment between reported status and physical codebase state.

Audits conducted across `tuna-os` repositories revealed systemic failure modes where issues tracking technical debt, God-file refactors, and committed-artifact removal were closed prematurely without satisfying their stated acceptance criteria. This resulted in invisible technical debt accumulation, false completion metrics, and regression drift.

This policy defines empirical verification standards required before any issue may be closed as `COMPLETED` or `NOT_PLANNED`.

---

## ⚠️ 2. Identified Failure Modes & Anti-Patterns

Any issue closure falling into the following categories constitutes a process failure:

| Anti-Pattern / Failure Mode | Example | Cause & Consequence |
|---|---|---|
| **Partial Fix Marked COMPLETED** | Adding `.gitignore` line without running `git rm --cached` on tracked binaries | Blobs remain in git history/tree; issue is marked closed while repo bloat persists. |
| **Superficial Modularization** | Extracting minor helper/test files while the parent module remains >2,000 LOC | Stated goal of decomposing God-file is unmet; refactor tracking disappears. |
| **Overstated Rationale** | Claiming tool consolidation when 0 of N downstream consumers have migrated | Tracking is closed before dependent integrations complete. |
| **Silent `NOT_PLANNED` Closure** | Closing an issue with an empty comment or agent signature block without explanation | Obscures why work was dropped and whether it was superseded or forgotten. |

---

## 📐 3. Verification Standards for `COMPLETED`

An issue may only be transitioned to `COMPLETED` when empirical evidence demonstrates that every acceptance criterion has been met.

### 3.1. Objective Acceptance Criteria by Issue Type

1. **Refactor & God-File Splitting**:
   - Stated LOC limits and submodule structure must be verified.
   - Example verification: `wc -l path/to/module.rs` demonstrates module size is within the agreed threshold (<500 LOC or as specified).
2. **Tracked Artifact / Large File Removal**:
   - `git ls-files <path>` must return 0 results.
   - Repository size caps and `.gitignore` entries must both be verified.
3. **Tool Consolidation & Deprecation**:
   - 100% of consumer repositories/modules must be migrated before closing the consolidation tracker.
   - Deprecated packages must carry explicit deprecation notices and updated crate/package names.
4. **Bug & Regression Fixes**:
   - A regression test reproducing the failure prior to the fix must pass in CI.

### 3.2. PR Linking as Primary Closure Mechanism
- Refactor and code change issues **must** be closed via GitHub keyword linking in PR descriptions (e.g., `Fixes #1234` or `Closes #1234`).
- Automatic closure on PR merge ensures that code has passed CI gates and code review before the issue is closed.
- Manual issue closure without an associated PR should only occur when no code change was required, and **must** include an empirical verification comment.

---

## 🚫 4. Mandatory Rationale for `NOT_PLANNED`

Closing an issue as `NOT_PLANNED` is a legitimate decision, but it **strictly requires a written rationale sentence**. Empty comments, agent signature-only comments, or closures without commentary are forbidden.

Acceptable rationales include:
- **Superseded**: Specify the superseding issue/PR number (e.g., `"Superseded by #156–#163 which decomposes this into granular sub-issues."`).
- **Won't Fix**: State the technical or strategic rationale (e.g., `"Won't fix: upstream component X is deprecated in favor of Y."`).
- **Obsolete**: Document the architecture change rendering the issue moot (e.g., `"Obsolete: workflow migrated to native container runner in #450."`).

---

## 📋 5. Issue Template Requirements

All architect, refactor, and bug issue templates must include a mandatory Acceptance Criteria checklist.

```markdown
### Acceptance Criteria
- [ ] Explicit measurable criterion 1 (e.g., `crates/foo/src/main.rs` <= 500 LOC)
- [ ] Explicit measurable criterion 2 (e.g., `git ls-files path/to/artifacts` returns empty)
- [ ] CI validation passes without error suppression
```

---

## 🛡️ 6. Automated Guards & Organization Sweeps

1. **CI Artifact Guards**:
   - Repositories that removed committed binary artifacts must include a CI lint step validating `git ls-files` against known banned patterns to prevent accidental re-commit regressions.
2. **Architect Re-Measurement Sweeps**:
   - Periodic architect agent sweeps will sample recently closed issues, re-measure physical repository state against original issue acceptance criteria, and re-open issues found to have closed without meeting criteria.
