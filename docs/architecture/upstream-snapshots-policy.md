# Architectural Standards: Upstream Snapshot Vendoring, Tracking, & Repository Hygiene Policy

**Status**: APPROVED (Active Architectural Policy)  
**Tracks**: [#1647](https://github.com/tuna-os/tunaOS/issues/1647) (_upstream-snapshots/ vendored wholesale policy & tracking)  
**Owner**: Architecture / Scanner  
**Applies to**: `_upstream-snapshots/`, `scripts/sync-upstream-snapshots.sh`, and `.github/workflows/snapshot-upstreams.yml`  

---

## 1. Executive Summary

TunaOS tracks sibling upstream projects (`aurora`, `bluefin-lts`, `zirconium`) to identify relevant container build updates, system configurations, and package changes for downstream adaptation.

### Current Implementation & Challenges
- **Wholesale Tree Vendoring**: Upstream files are mirrored into `_upstream-snapshots/<upstream-name>/`. Currently, this includes **241 files totalling 1.9 MB** committed directly into git history.
- **Git History Bloat**: On every scheduled refresh via `.github/workflows/snapshot-upstreams.yml`, snapshot updates commit entire trees. Even minor upstream changes can cause cascading git blob bloat over time.
- **Review Surface Overhead**: Wholesale commits force code reviewers to inspect large multi-file diffs rather than focused delta surfaces of relevant files.
- **Tooling Inefficiencies**: Repository linters and build recipes require repetitive manual exclusions (e.g. `find . -not -path './_upstream-snapshots/*'`) to avoid running checks against upstream third-party code.

This policy defines strict content filtering, file count and size gates, centralized repository hygiene rules, and the target manifest/artifact-based tracking architecture.

---

## 2. Architectural Objectives

1. **Focused Delta Tracking**: Track only the precise paths relevant to TunaOS container builds and system files, discarding unrelated upstream documentation, CI pipelines, and tests.
2. **Git History Protection**: Enforce strict size and file count budgets on `_upstream-snapshots/` to prevent monotonic repository growth.
3. **Streamlined Review Surface**: Ensure automated snapshot pull requests highlight actionable code diffs rather than hundreds of unrelated upstream file changes.
4. **Standardized Tooling Exclusions**: Consolidate tool exclusions into root configuration files rather than scattered ad-hoc command-line parameters.

---

## 3. Scope & Content Inclusion Rules

`scripts/sync-upstream-snapshots.sh` must apply strict whitelist filtering when rsyncing files from upstream default branches:

### 3.1 Allowed Paths (Inclusions)
Only files directly impacting container build configurations or system runtime definitions may be snapshotted:
- `build_files/` (container build scripts and package installation routines)
- `system_files/` (systemd units, desktop config overrides, policy definitions)
- `Containerfile*` / `Dockerfile*` (OCI image build definitions)
- `packages.json` / package list manifests

### 3.2 Prohibited Paths (Exclusions)
The following directories and patterns must be strictly excluded from snapshots:
- Documentation: `docs/`, `*.md`, `*.png`, `*.svg`, screenshots
- CI/CD Configurations: `.github/`, `.gitlab-ci.yml`, CI helper scripts
- Test Suites: `tests/`, `*.bats`, `*.py`, test fixtures
- Release tooling and changelog generators
- Binary artifacts and ISO builder assets

---

## 4. Size Budgets & Gate Enforcement

To prevent unbounded repository growth, size and file count gates are enforced during snapshot updates:

### 4.1 Budget Limits

| Target Upstream | Max File Count Budget | Max Size Budget |
|---|---|---|
| `_upstream-snapshots/aurora` | ≤ 100 files | ≤ 600 KB |
| `_upstream-snapshots/bluefin-lts` | ≤ 100 files | ≤ 600 KB |
| `_upstream-snapshots/zirconium` | ≤ 100 files | ≤ 800 KB |
| **Total `_upstream-snapshots/` Tree** | **≤ 250 files** | **≤ 2.0 MB** |

### 4.2 Gate Enforcement Mechanism
The synchronization script (`scripts/sync-upstream-snapshots.sh`) and CI workflow (`.github/workflows/snapshot-upstreams.yml`) must enforce these budgets:
1. After syncing, compute total file count (`find _upstream-snapshots/ -type f | wc -l`) and total disk footprint (`du -sk _upstream-snapshots/`).
2. If the snapshot exceeds the budget ceiling, the script aborts with a non-zero exit code and emits a diagnostic breakdown of oversized files.
3. PR generation is blocked until filter rules are adjusted or oversized upstream inclusions are pruned.

---

## 5. Storage Architecture & Manifest Evolution

### Phase 1: Filtered In-Tree Snapshots (Current)
- Enforce strict path whitelisting and size budgets directly within `scripts/sync-upstream-snapshots.sh`.
- Commit only filtered, delta-relevant files alongside `.snapshot.json` metadata (tracking upstream commit SHA, date, and source repository).

### Phase 2: Manifest-Driven External Artifact Tracking (Target)
- Transition full upstream trees out of git history into versioned OCI artifacts on GHCR (e.g. `ghcr.io/tuna-os/upstream-snapshots/<name>:<commit-sha>`).
- The git repository commits only `.snapshot.json` manifests:
  ```json
  {
    "upstream": "ublue-os/aurora",
    "commit": "a1b2c3d4e5f6...",
    "synced_at": "2026-08-29T21:00:00Z",
    "artifact_uri": "ghcr.io/tuna-os/upstream-snapshots/aurora:a1b2c3d4"
  }
  ```
- Snapshot refresh workflows generate focused diff summaries in the PR description, showing only the diff between the previous and current snapshot digests.

---

## 6. Repository Hygiene & Linter Policy

1. **Read-Only Invariant**: Files under `_upstream-snapshots/` are strictly read-only mirrors. No manual edits, local patches, or downstream modifications may be committed directly to `_upstream-snapshots/`. All customization must occur in `build_files/` or `custom/`.
2. **Centralized Tool Configuration**:
   - Linters (`shellcheck`, `actionlint`, `yamllint`, `pytest`) must configure `_upstream-snapshots/` exclusions in their respective configuration files (`.yamllint`, `pytest.ini`, `.editorconfig`) rather than requiring callers to pass ad-hoc `-not -path` flags.
3. **Upstream Lifecycle Management**:
   - If an upstream project is deprecated or superseded, its directory under `_upstream-snapshots/` must be removed to reclaim repository footprint.
