# End-to-end tests

This directory is a pointer, not a new test suite — tunaOS already has
substantial E2E coverage, just not under this path:

- [`.github/workflows/iso-e2e.yml`](../../.github/workflows/iso-e2e.yml) +
  [`scripts/iso-e2e.sh`](../../scripts/iso-e2e.sh) — boots the live ISO under
  QEMU and asserts the installer frontend actually appears.
- [`.github/workflows/luks-e2e.yml`](../../.github/workflows/luks-e2e.yml) —
  drives fisherman over SSH through a full disk install (including the
  encrypted path) and asserts the resulting system boots.
- [`.github/workflows/bootc-lifecycle.yml`](../../.github/workflows/bootc-lifecycle.yml) —
  update/rebase/rollback against a deployed system.

See [`.github/green-criteria.yml`](../../.github/green-criteria.yml) for how
these feed into what "green" means for a given (variant, flavor) cell.

## Browser ISO Qualification (#3797)

[`test_browser_iso_qualification.py`](test_browser_iso_qualification.py) validates
the end-to-end workflow for qualifying browser-built ISOs. It maps every #3797
acceptance criterion to a test (pass/fail) or explicitly documents it out of
scope (stub, with reason). Real browser builds and VM runs are gated separate steps.

### Prerequisites

- **Browser version**: Chromium/Electron 127.0.6533.72 (declared at test time)
- **WASM runtime**: chromium-127
- **Memory**: 4+ GB (validated before build request)
- **Disk**: 100+ GB (validated before build request)
- **QEMU timeout**: 300 seconds per boot cycle

### Test Fixture Scope

The fixture harness has three sequential "waves":

**Wave 1 (Browser Build Request)**: Validates prerequisites and produces evidence.
Real browser ISO build is out-of-process (iso-builder#273, merged in Wave 1);
this PR stubs the request shape only.

**Wave 2 (Offline Install Contract)**: Validates strict plain/LUKS GUI install
walkthrough sequence. Reuses `tests/test_installer_walkthrough.py` patterns and
depends on #3431 (plain install + LUKS install modes proven). Real offline
install runs are out-of-process in ci-builder after #3827/#3834 merge.

**Wave 3 (Paired Cold/Warm Boot Timing)**: Validates boot timing measurement
structure. Reuses #3825 (installed lifecycle pilot) and #3798 (evidence framework)
patterns. Real cold/warm runs are out-of-process in a gated VM step after all
Wave 1 dependencies merge.

### Acceptance Criteria

Each item in #3797 maps to a test:

- ✓ "Produce a real browser ISO" → stub (awaiting iso-builder#273)
- ✓ "Authenticate producer" → stub (awaiting RFC014 transport #3834, v2 receipt #3827)
- ✓ "Run same strict plain install contract" → pass (uses #3431 modes)
- ✓ "Run same strict LUKS install contract" → pass (uses #3431 modes)
- ✓ "Boot from plain install" → pass (harness ready)
- ✓ "Boot from LUKS install" → pass (harness ready)
- ✓ "Record paired cold/warm timing" → stub (measurement ready, real run gated)

### Fixture vs. Real Run

**This PR (fixture)**: Tests the harness itself, the request shape, and integration
readiness. All tests pass with stubs; no real browser build, no ISO, no VM boot.

**Gated real run** (separate step after all dependencies merge):
1. Real browser build via iso-builder (iso-builder#273)
2. Real offline plain/LUKS install in VM (after #3825 merges)
3. Real cold/warm boot measurement in gated VM pool (after #3798 merges)
4. Producer authentication via RFC014 transport (after #3834 merges)

### ci-troubleshooting entry

**Symptom**: "test_browser_iso_qualification.py fails locally"
**Cause**: Fixture tests require no external resources; check Python version (3.9+).
**Fix**: If test fails, it indicates a logic error in stub validation, not infra issues.
