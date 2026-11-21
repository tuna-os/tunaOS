---
created_date: "2026-10-20"
document_status: draft
---

# Plan: 20261020033411-x13s-external-media

<!-- Created: 2026-10-20T03:49:08.710656+00:00 -->
<!-- Commit: 83362754 -->
<!-- Branch: codex/x13s-external-media -->
<!-- Repository: tuna-os/tunaOS -->

## Overview

Prepare verifiable external live media for the ThinkPad X13s owner. Include the board payload and correct boot chain, prevent automatic internal-storage mounting, and keep inspected artifact delivery separate from physical support qualification.

## Conventions

- **Main is canonical** — rebase existing profile work and coordinate concurrent configuration changes.
- **Assert applied effects** — inspect actual firmware, initramfs, EFI architecture and kernel/DTB pairing.
- **Keep qualification gates** — source checks and generic VM boots cannot satisfy X13s hardware criteria.
- **Central tool pins** — update image-versions or its migrated primary equivalent, never workflow literals.
- **Regression coverage** — incident tests include a Falsification line and behavioral rejection cases.
- **Guard destructive paths** — first live tests suppress internal automount and exclude installation.
- **Mandatory fix/check and STE budget** — run normal repository checks without raising budgets.
- **Troubleshooting evidence** — record symptom, cause and fix for loader and firmware failures.
- **Generated files** — regenerate adapters and lanes from the agreed primary configuration.

## Architecture & Design Decisions

Use three bounded changes: Fedora board payload in tunaOS, architecture-correct native boot-chain support in Tacklebox, and artifact inspection plus owner guidance in tunaOS. Preserve the W1-selected Fedora shim/GRUB/Fedora kernel-uki-dtbloader payload direction, subject to inspecting its actual package layout and kernel selection. Package inclusion, initramfs inclusion and successful physical use remain separate observations. Applied-effect and evidence conventions require checking final bytes rather than only recipes.

The first deliverable is experimental external live media. Keep installed bootc/Fisherman update and rollback as a later gate, while verifying that the chosen payload has a viable lifecycle before implementing installation support. Follow the central-pin convention when advancing Tacklebox and preserve its deadline/floor fixes. Coordinate profile data with the TOML migration rather than adding a competing configuration source.

A direct native loader change is higher effort than a pin-only upgrade, but the inspected current main still lacks native Fedora GRUB support. A browser-only first implementation is medium-to-high effort and aligns with the long-term delivery direction, but its current evidence API work does not prove native boot payload or device support. Use the existing experimental build path for initial inspection without creating a permanent distribution stream. See research.md#alternatives-considered-and-rejected. Trust verification covers component and media integrity; Secure Boot remains unproven.

## Component Breakdown

- X13s overlay owns stock-kernel verification, packaged board firmware, early-driver inclusion and persistent board arguments. It emits an inventory consumed by artifact inspection.
- Native Tacklebox payload staging owns target-architecture EFI selection, kernel/DTB pairing and the selected loader chain. It must reject missing or mismatched inputs before emitting media.
- TunaOS recipe adapter passes the reviewed hardware profile into the builder without changing unrelated flavors.
- Artifact inspector verifies final EFI, kernel, initramfs, DTB selection and argument bytes, and binds them to exact source/image/builder/media identities.
- Owner guide and result template provide reversible external boot steps, internal-storage precautions and separate live/installed results.
- Bootc/Fisherman lifecycle integration owns later external installation, update and rollback continuity; its physical completion is not a prerequisite for an explicitly live-only first artifact.

## Data Structures & Interfaces

- Hardware boot profile: explicit target architecture, loader mode, required kernel-matched DTB identity and approved kernel arguments. The builder rejects unsupported combinations; generic profiles keep their existing defaults.
- Payload inventory: package NEVRA/ownership, kernel release, firmware names and compression, module/builtin status, initramfs membership, EFI architecture and loader selection evidence. Missing items remain missing, never inferred from package names.
- Artifact receipt: source SHA, immutable image digest, builder SHA, media size/hash and verification results. Reuse the existing provenance contract where applicable without presenting native media as browser-produced evidence.
- Owner result: exact artifact identity, device model/firmware observations, temporary boot selection, boot outcome, observed peripherals and failure logs. Private identifiers are removed before sharing. Live boot, external installation and update/rollback are separate fields.

## Implementation Detail

Keep the overlay linear: install verified Fedora packages, establish board configuration, rebuild the matching non-hostonly initramfs, then inspect final contents. Required firmware or early driver failures stop the build; optional peripheral observations do not become boot qualification. Use module-versus-builtin checks so a working built-in driver is not treated as a missing module.

Make boot payload selection an explicit builder boundary. Select image-provided, target-architecture bytes and verify kernel/DTB pairing before staging. Never fall back silently to the build host's x64 loader. Preserve signed executable bytes and collect signature/trust observations without claiming firmware acceptance. Keep generic profiles behaviorally compatible.

The final-media inspector examines the emitted artifact independently from recipe generation. It rejects absent/mismatched loader components, wrong architecture, unapproved arguments and stale kernel/DTB pairings. Owner guidance is generated or checked against that exact artifact receipt; internal automount suppression is part of the media, with a clear warning that manual mounting can write to internal storage.

## Dependencies

- W1 PR3389 / issue3377 — supplies the image-only ARM64 profile; actual child digest and report must be captured before closing W1.
- Fedora kernel, Fedora kernel-uki-dtbloader payload, qcom-firmware, atheros-firmware and dracut — provide runtime payload; verify current package ownership, licenses and actual bytes before changing the overlay.
- Tacklebox native builder — must gain the selected target-architecture loader path before media delivery; upgrade the central pin only after reviewed tests and ancestry checks.
- Bootc/Fisherman — verify installed GRUB ownership and kernel/DTB update/rollback behavior before installation support. No unrelated x64 fallback rewrite is assumed necessary.
- Primary TOML migration — preserve ARM64-only and false ISO/QCOW2/LUKS flags; coordinate schema and generated adapters with that work.
- Existing provenance contract and browser work — reuse identity vocabulary while preserving native/browser separation; browser API work is independent of native payload implementation.
- RFC/signing/qualification policies — preserve approval and integrity requirements; no Secure Boot assertion follows from hashing bytes.
- Design documents this plan was built on: none registered (refs empty, unresolved zero). The W1 issue records technical direction; a new binding design still needs repository review.

## Testing Approach

Use behavioral pytest/Bats for overlay and recipe effects, Go unit/fixture tests for builder staging, and final-artifact integration checks. Give loader selection and stale kernel/DTB rejection the most coverage because a plausible inventory can conceal unbootable media. Exercise compressed firmware, shared symlinks, missing payloads, built-in versus modular drivers, cross-architecture hosts, signed-byte preservation and argument propagation. Incident regressions follow the repository Falsification convention; no existing gate is disabled.

Artifact integration must inspect EFI architecture and chain, embedded DTB/CHID selection, kernel release, initramfs contents and effective arguments. Generic ARM64 QEMU tests can reject packaging errors but cannot establish SC8280XP boot success. Test automount suppression in the actual live desktop and verify no automatic installer runs. Normal repository formatting, lint and tests remain required.

Success metrics:
- Owner completes the external live test with exact artifact identity: Manual — captured in the implementation test plan.
- Existing internal installation remains usable and unchanged: Manual — captured in the implementation test plan. Automated live-policy tests cover no automatic mounting or installation but cannot substitute for the device observation.
- Every published support claim has matching artifact or physical evidence: behavioral tests reject incomplete evidence mappings; final publication review is Manual — captured in the implementation test plan.

Physical Wi-Fi, audio, brightness, suspend, camera, Secure Boot and installed update/rollback outcomes are deliberate remaining gaps until separately authorized tests provide results. Delivering inspected experimental media does not close those gates.

## Milestones & Phases

### Milestone 1: Inspect a complete X13s board payload
The inspection image includes the required packaged firmware, early drivers and approved board arguments. Maintainers can see exact missing or present contents before anyone attempts a device boot. This is build groundwork, not a hardware-support claim.

Validation point: actual image digest, package ownership/license report and kernel-matched initramfs inventory pass the required-payload checks.

#### - [ ] Phase 1.1: Verify and include the board payload
**Repo:** tunaos

Inspect the built Fedora image and confirm package ownership, licenses and loader layout before adding the required board payload. Add early-driver and argument configuration only where actual kernel and package evidence supports it.

*Technical detail:* [context.md#phase-11](./context.md#phase-11-verify-and-include-the-board-payload)

**Acceptance criteria**:
- [ ] Required firmware and early drivers are present in the matching final initramfs.
- [ ] Package ownership, licenses and effective arguments are recorded against an immutable image digest.
- [ ] Missing payloads and unsupported combinations fail before media construction.

### Milestone 2: Obtain inspected experimental external media
The owner can obtain media whose target-architecture boot chain and kernel/DTB pairing have been checked. Guidance identifies the exact artifact, trust evidence and limitations. No permanent download stream or support label is introduced.

Validation point: reviewed builder changes, final-media inspection, generic packaging smoke checks and internal automount policy tests pass; the first artifact is available with its receipt.

#### - [ ] Phase 2.1: Implement and review native X13s loader support
**Repo:** tacklebox (external dependency repository)

Implement an explicit native Fedora loader mode with image-provided ARM64 bytes and kernel-matched DTB selection. Review installed lifecycle viability before locking its interface, then review the implementation and tests before TunaOS consumes its revision.

*Technical detail:* [context.md#phase-21](./context.md#phase-21-implement-and-review-native-x13s-loader-support)

**Acceptance criteria**:
- [ ] The native loader API explicitly selects the reviewed Fedora chain and rejects unsupported combinations.
- [ ] Cross-host fixtures select ARM64 image bytes and never silently substitute host x64 loaders.
- [ ] Signed chain bytes are preserved and stale or mismatched kernel/DTB pairs are rejected.
- [ ] Installed lifecycle ownership has a viable reviewed design, with physical completion still open.
- [ ] A reviewed Tacklebox commit and passing native tests exist before TunaOS pin integration.

#### - [ ] Phase 2.2: Integrate a verified native boot chain
**Repo:** tunaos

Consume reviewed Tacklebox support for the chosen Fedora loader chain and verify the actual emitted media. Keep the profile unavailable for normal ISO admission until those checks pass.

*Technical detail:* [context.md#phase-22](./context.md#phase-22-integrate-a-verified-native-boot-chain)

**Acceptance criteria**:
- [ ] The image supplies the correct ARM64 EFI chain and kernel-matched DTB selection.
- [ ] Wrong-architecture loaders, stale DTBs and missing components are rejected.
- [ ] Builder pin updates preserve existing deadline and compatibility guarantees.
- [ ] Final media has a verifiable identity receipt and explicit experimental status.

#### - [ ] Phase 2.3: Make the first live session safe to inspect
**Repo:** tunaos

Suppress automatic internal-storage mounting and automatic installation in the first test session. Supply artifact-specific instructions, integrity checks, stop conditions and a result template.

*Technical detail:* [context.md#phase-23](./context.md#phase-23-make-the-first-live-session-safe-to-inspect)

**Acceptance criteria**:
- [ ] The actual live session does not automatically mount internal storage or start installation.
- [ ] Guidance explains manual-mount write risk and temporary boot selection without persistent boot/security changes.
- [ ] Exact artifact identity, known limits and recovery instructions accompany the download.

### Milestone 3: Record the owner's first reversible live test
The owner has a bounded checklist for temporary external boot and can return a useful result without installation or internal-disk mounting. Hardware claims advance only for observations actually reported.

Validation point: a result tied to the exact artifact records boot behavior and confirms the existing internal installation remains usable; later external installation/update/rollback gates remain explicit.

#### - [ ] Phase 3.1: Record owner evidence and keep remaining gates visible
**Repo:** tunaos

The owner runs the bounded live checklist and returns observations for the exact media. Record only supported results, with later external installation, update and rollback tracked separately.

*Technical detail:* [context.md#phase-31](./context.md#phase-31-record-owner-evidence-and-keep-remaining-gates-visible)

**Acceptance criteria**:
- [ ] The result identifies the exact artifact and actual X13s model.
- [ ] The owner records live-boot behavior and the internal installation's continued usability.
- [ ] Unsupported or untested features remain explicit open gates.

## Open Questions

Published Fedora 44 metadata and checksum-verified RPMs confirm kernel-uki-dtbloader-7.2.11-200.fc44.aarch64 exists and conflicts with matching kernel-core. The reviewed investigation is live-only immutable loader input alongside retained stock kernel-core, avoiding a package transaction. Its .linux payload exactly matches published kernel-core vmlinuz; final image identity, native GRUB handoff and module ABI remain acceptance gates. See [loader-contract.md](./loader-contract.md) for the measured candidate and trust limits. Installed replacement/lifecycle design is a separate future decision.

USB-C root safety is also blocking: upstream dracut PR2302 supplies a pre-udev ADSP hook to reset Type-C before storage is mounted. Check the exact Fedora dracut package and final Tacklebox-rebuilt initramfs for this ordering. Missing proof blocks external-media delivery; do not use a permanent remoteproc blacklist as an unreviewed substitute.


The emitted Fedora image's exact loader layout, CHID match and early firmware behavior require the first artifact inspection. If those contradict the selected stock-kernel loader direction, stop dependent implementation and obtain a revised reviewed design rather than copying a fixed DTB or switching kernels silently.

Actual X13s live behavior and the internal installation's unchanged usability require owner observations. A failed or ambiguous result keeps the physical gate open; collect bounded logs before recommending another attempt. Installed update/rollback behavior requires a later separately authorized external-disk test.

## Out of Scope

- Internal-disk installation, partitioning or ESP writes; the first artifact is live-only.
- Persistent firmware/boot-security changes, flashing, modem unlocks or extraction of Windows firmware.
- Claims for Secure Boot, TPM unlock, suspend, camera, KVM, X Elite or other hardware without their own evidence.
- Full installed plain/passphrase-LUKS qualification and update/rollback completion; retain those later gates under epic3368.
- A new permanent artifact stream, hosted service or local CLI as the primary distribution path; preserve the browser direction.
- Browser provenance API implementation owned by the parallel browser work; this plan only coordinates identity boundaries.
- Lowered signing, qualification, test or prose gates to make the profile appear ready.



## Published loader audit update (2026-10-20)

The official Fedora updates candidate is available; package absence is no longer the blocker. The candidate loader uses systemd-stub 259.9-1.fc44. Its meaningful .linux payload and published stock kernel-core vmlinuz both have size 17,365,352 and SHA256 f838299696f91f0400de9e6b796d3d862f8e9eb2899101a913314150ce9550d6. Kernel-core, modules-core and loader metadata name the same kernel-7.2.11-200.fc44.src.rpm. This is candidate-package evidence, not evidence of the eventual root image.

The proposed live-only interface accepts separately pinned loader bytes without replacing kernel-core. Actual selected-stub GRUB/LoadFile2 boot, final module ABI, CHID choice, PE signature verification, redistribution materials and final ADSP initramfs ordering remain blocking checks. The complete inspected dracut108-8.fc44 package set lacks the named upstream ADSP hook and equivalent qcom_q6v5_pas/sc8280xp shell logic; final emitted initramfs remains decisive. No production consumer or admission changes are made.
