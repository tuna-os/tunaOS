# Failure-Injection Suite: Break the Factory on Purpose

Part of Hive practice #4 in epic #2250 (issue #2258).

This directory houses intentional failure-injection tests that simulate real-world infrastructure and supply chain incidents recorded in `.github/green-criteria.yml`.

## The Five Invariant Properties

Every failure-injection test MUST assert that when an injected failure occurs, the pipeline:

1. **(1) Fails:** The offending check, script, or workflow step exits with a non-zero exit status code.
2. **(2) Says why:** The failure output or error diagnostics explicitly name the failure reason (e.g. HTTP status, missing package name, architecture mismatch, timeout marker, `SIGSTORE_OUTAGE`).
3. **(3) Does not call the cell green:** The composite status scoring (`scripts/gen-matrix-status.py` against `.github/green-criteria.yml`) evaluates the affected cell as not green (verdict `fail` or `untested`, never `pass`).
4. **(4) Does not promote:** Promotion conditions (`tag-image` in `.github/workflows/reusable-build-image.yml`) prevent publishing bare tags or unverified images to the registry.
5. **(5) Keeps enough evidence to diagnose:** Logs, error messages, serial console captures, or wishlist files retain necessary context for human maintainers or automated recovery mechanisms (e.g. `rerun-infra-failures.yml`).

## Incident Coverage

| Test Module | Incident | Injected Failure Mode | Target Script / Gate |
|---|---|---|---|
| `test_base_image_gc.py` | #1788 | Base image digest garbage-collected upstream (HTTP 404) | `scripts/check-base-image-pins.sh` |
| `test_package_repo_outage.py` | #391 | Package repository 404/503 mid-build / nightly | `scripts/check-package-repo-pins.py`, `build_scripts/lib.sh` |
| `test_declared_arch_missing.py` | #1755 §3 | Declared platform missing from base manifest | `scripts/check-base-image-pins.sh` arch honesty |
| `test_requested_package_missing.py` | #858 | Required desktop package dropped silently | `build_scripts/checks/verify-package-wishlist.sh`, `lib.sh` |
| `test_sigstore_rekor_outage.py` | #1560 | Sigstore Rekor transparency log 5xx outage | `.github/scripts/cosign-retry.sh`, `reusable-build-image.yml` |
| `test_qemu_boot_timeout.py` | #1811 | QEMU VM boot hang / contract marker timeout | `scripts/iso-e2e.sh --disk` |
| `test_push_failure.py` | — | OCI registry push failure mid-layer upload | `scripts/build-image-inner.sh` |
| `test_disk_full.py` | — | Build host disk quota exhaustion (ENOSPC) | `scripts/build-image-inner.sh` / build operations |
