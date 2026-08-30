# Image Factory Completion Gate & Definition of Done (#1283)

This document establishes the unified **Image Factory Completion Gate** and **Definition of Done** for all supported TunaOS variants (`.github/build-config.yml`).

## 1. Goal

Deliver a fully functional TunaOS image factory in which every supported variant is built, published, installable, bootable, updateable, recoverable, and backed by fresh automated evidence.

## 2. Definition of Done (Per Variant × Flavor × Platform)

For every supported `variant × flavor × platform` cell:

- [x] **OCI Build & Publish**: OCI image builds reproducibly and publishes by immutable digest (`ghcr.io/tuna-os/<variant>@sha256:...`).
- [x] **Package & Desktop Contracts**: Passes package/desktop contract checks via `verify-desktop-experience.sh` (Desktop Contract Sweep).
- [x] **Declared Outputs**: All declared outputs (OCI / ISO / QCOW2 / hardware installer) are generated and discoverable.
- [x] **Boot Verification**: Each declared output boots and reaches its expected desktop or service contract.
- [x] **Install-to-Disk & LUKS**: Complete install-to-disk, reboot, and first boot verified (`luks-e2e.yml`).
- [x] **Lifecycle Stream Operations**: Published streams pass bootc `update`, `rebase`, and `rollback` validation (`bootc-lifecycle.yml`).
- [x] **Supply-Chain Verification**: Enforceable keyless Cosign v3 signatures, SPDX SBOMs, and provenance attestations attached and verified ([VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md)).
- [x] **Fresh Evidence**: Automated evidence is fresh, linked, and required for stable promotion ([MATRIX-STATUS.md](MATRIX-STATUS.md)).
- [x] **Failure Visibility**: Scheduled failures cannot be hidden by aggregate workflow status or silent skips.
- [x] **Catalog & Artifact Currency**: User-facing catalog, documentation, release assets, and checksums agree.

## 3. Integrated Factory-Wide Gates

1. **Lifecycle Ledger & Ledger Gate (`#1278`, `#1283`)**:
   - `scripts/gen-matrix-status.py` regenerates `docs/MATRIX-STATUS.md` tracking LUKS E2E, Desktop Contract, Bootc Lifecycle, and Installer Smoke.
2. **Installer Coverage (`#1279`)**:
   - `scripts/e2e-installer-gui-checks.sh` derives installer frontend test coverage from declared capabilities.
3. **Bootc Update/Rebase/Rollback (`#1280`)**:
   - `.github/workflows/bootc-lifecycle.yml` validates stream updates, variant/desktop rebases, and rollback recovery.
4. **Browser & On-Demand ISO Parity (`#1281`)**:
   - Browser ISO generator (`publish-iso-groups.yml`) aligns with on-demand tacklebox builds.
5. **Supply Chain Enforcement (`#1187`, `#1193`)**:
   - Cosign keyless OIDC signing, SPDX SBOM attestations, and ISO verification bundles ([VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md)).
6. **Release Currency & Lifecycle Admission (`#1254`, `#1175`, `#1196`, `#1270`)**:
   - Strict admission criteria for new variants/flavors before matrix expansion.
7. **Install & Hardware Verification (`#979`, `#1099`, `#989`, `#777`, `#781`)**:
   - Asahi Apple Silicon (`scripts/verify-asahi-image.sh`) and Intel T2 hardware qualification runs.

## 4. Current Matrix Verification References

- **LUKS E2E & Desktop Contract Ledger**: [MATRIX-STATUS.md](MATRIX-STATUS.md)
- **Pipeline & Build Architecture**: [PIPELINE.md](PIPELINE.md)
- **Artifact Verification Guide**: [VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md)
