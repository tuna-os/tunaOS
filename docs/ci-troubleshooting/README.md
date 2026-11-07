# CI Troubleshooting Playbook

Last updated: 2026-07-16 (by `fix/r2-cost-reduction` investigation)

Quick reference to diagnose CI failures that recur. A branch-integration push
that touched 36 files across `.github/`, `build_scripts/`, `live-iso/`,
`scripts/`, and `tests/` surfaced them.

---

The playbook has one file for each topic.
To search all files, run `grep -rn "<symptom>" docs/ci-troubleshooting/`.

## Index

### [Failure Catalog](failure-catalog.md)

Symptom table (numbered rows) and the first catalogue of failures.

- [`Failure Catalog`](failure-catalog.md#failure-catalog)

### [Boot Diagnostics and Gate Workflow](boot-diagnostics.md)

How a boot is built and read: components, commands, serial logs, the build gate.

- [`Glossary of Components`](boot-diagnostics.md#glossary-of-components)
- [`Diagnostic Commands`](boot-diagnostics.md#diagnostic-commands)
- [`Reading a published image without a container runtime`](boot-diagnostics.md#reading-a-published-image-without-a-container-runtime)
- [`Serial Log Deep Diagnosis`](boot-diagnostics.md#serial-log-deep-diagnosis)
- [`Key Files in the Boot Chain`](boot-diagnostics.md#key-files-in-the-boot-chain)
- [`Critical architectural insight: IMAGE vs OSTREE DEPLOYMENT`](boot-diagnostics.md#critical-architectural-insight-image-vs-ostree-deployment)
- [`Build Gate Workflow`](boot-diagnostics.md#build-gate-workflow)

### [Confirmed Gate Failures](confirmed-gate-failures.md)

Gate failures with a known cause and fix, numbered 9 and up.

- [`Confirmed Gate Failures (2026-07-15)`](confirmed-gate-failures.md#confirmed-gate-failures-2026-07-15)
- [`31. Installed runtime report rejects a desktop`](confirmed-gate-failures.md#31-installed-runtime-report-rejects-a-working-desktop-with-starting)
- [`32. Weekly boot report hides successful non-GNOME QCOW2 captures (#2801)`](confirmed-gate-failures.md#32-weekly-boot-report-hides-successful-non-gnome-qcow2-captures-2801)

### [Workflow, Fork, Package and Matrix Failures](workflow-and-fork-failures.md)

Failures in workflows, forks, packages, the STE budget and the matrix board.

- [`Fork source pin changes after tests`](workflow-and-fork-failures.md#fork-source-pin-changes-after-tests)
- [`Fork preview reuses stock packages/art or rejects a changed checkout`](workflow-and-fork-failures.md#fork-preview-reuses-stock-packagesart-or-rejects-a-changed-checkout)
- [`Package authoring refuses an add or asks for an editor dependency`](workflow-and-fork-failures.md#package-authoring-refuses-an-add-or-asks-for-an-editor-dependency)
- [`Package addition conflicts with a DNF exclusion or exceeds the size limit`](workflow-and-fork-failures.md#package-addition-conflicts-with-a-dnf-exclusion-or-exceeds-the-size-limit)
- [`Workflow inherits repository token defaults (#2916)`](workflow-and-fork-failures.md#workflow-inherits-repository-token-defaults-2916)
- [`` Content PR fails with `STE budget exceeded` (#2912) ``](workflow-and-fork-failures.md#content-pr-fails-with-ste-budget-exceeded-2912)
- [`Matrix board and provenance disagree after a merge (#3813)`](workflow-and-fork-failures.md#matrix-board-and-provenance-disagree-after-a-merge-3813)
- [`Rustup version changed but installer hashes stayed old`](workflow-and-fork-failures.md#rustup-version-changed-but-installer-hashes-stayed-old)
- [`Daily verification failure appears on a passing cell's issue`](workflow-and-fork-failures.md#daily-verification-failure-appears-on-a-passing-cells-issue)
