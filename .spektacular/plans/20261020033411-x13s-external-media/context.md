---
created_date: "2026-10-20"
document_status: draft
---

# Context: 20261020033411-x13s-external-media

## Current State Analysis

New source evidence: kernel-ark MR4318 uses kernel-uki-dtbloader, /lib/modules/<release>/vmlinuz-dtbloader.efi and an exact-version kernel-core conflict. These are proposal facts, not published package proof. Upstream dracut PR2302 merged as 647a685d on 2026-07-24, adding 70qcom-adsp/pre-udev priority30. Confirm Fedora backport and final initramfs; Tacklebox rebuilds the initramfs, so overlay-only inspection is insufficient.


PR3389 provides an image-only profile. Its repaired head dd54894a has no produced child digest yet. The ae93e9b native builder uses host-only x64-first EFI selection; current main has architecture-aware systemd-boot but not the selected native Fedora GRUB chain.

## Per-Phase Technical Notes

### Phase 1.1: Verify and include the board payload
- File changes: build_scripts/overlay/x13s.sh (from PR3389) installs verified Fedora qcom-firmware/atheros-firmware payload and writes board-scoped dracut/kargs configuration; tests/test_x13s_profile.py adds execution fixtures; docs/X13S-SUPPORT.md (from PR3389) records the actual package report. Do not invent module or karg values from this plan: obtain them from the epic and actual kernel/module evidence first.
- Required research output: RPM ownership/NEVRA/licenses, compressed firmware and symlink resolution, kernel config/module builtin status, actual Fedora kernel-uki-dtbloader payload PE sections/CHID and kernel release, full final initramfs membership. If the selected stock loader cannot satisfy W1, stop the dependent implementation and request a revised reviewed design.
- Tests: missing firmware, unsupported suffix, dangling link, builtin-versus-module driver, wrong kernel, absent initramfs member, exact karg persistence. Preserve all existing inspection cases.
- Complexity: High. Token estimate: ~30k. Agent strategy: parallel package/source analysis, sequential overlay integration.

### Phase 2.1: Implement and review native X13s loader support
- File changes in external tuna-os/tacklebox: internal/recipe/recipe.go adds an explicit validated loader-mode contract; internal/install/live.go and internal/install/bootchain.go select the target image's Fedora loader payload; internal/install/bootloader.go and internal/target/iso.go stage the complete boot chain and configuration. Exact loader package paths must come from phase1.1 artifact inspection.
- Add native Go fixture tests alongside these implementation files for ARM64 image selection on x64 hosts, missing shim/GRUB dependencies, opaque signed-byte preservation, unsupported modes and kernel/DTB mismatch. Preserve existing generic systemd-boot behavior and all builder deadline fixes.
- Ownership: the X13s engineering lane owns this separate Tacklebox patch/review dependency. Coordinate with the browser observation lane; no cmd/tbwasm or purefs provenance changes here. Inspect repository AGENTS and register the upstream checkout before implementation.
- Prerequisite design review: trace actual Bonito GRUB/bootc deployment ownership and Fisherman's chosen backend. Demonstrate how each updated or rolled-back kernel gets its matching DTB; no fixed ESP DTB copy. This is lifecycle viability review, not physical qualification.
- Output: reviewed upstream commit and exact native test receipts. Phase2.2 is blocked until that output exists.
- Complexity: High. Token estimate: ~40k. Agent strategy: parallel API/lifecycle analysis, sequential native implementation and independent review.

### Phase 2.2: Integrate a verified native boot chain
- File changes in tunaos: scripts/build-iso-tacklebox.sh:198 (profile-specific arguments/loader contract), image-versions.yaml downloads.tacklebox or its migrated TOML primary equivalent (central reviewed pin), tests/bats for the adapter, new tests/regressions/test_issue_3368_x13s_boot_payload.py and final-media inspector in scripts/.
- Dependency produced by phase2.1: separately reviewed tacklebox native changes around internal/install/live.go, internal/install/bootchain.go, internal/install/bootloader.go and internal/target/iso.go. The current pin ae93e9b has host-only x64-first EFI selection; main d36fdb84 improves architecture selection but has no native Fedora GRUB path. Require upstream fixture tests before integration. Do not edit cmd/tbwasm or browser provenance APIs in this phase.
- Verify exact image-provided shim/GRUB dependencies, loader kernel/DTB pairing and effective config in final ISO bytes, not just generated recipe text. Preserve opaque signed bytes; no Secure Boot success inference. Compare old generic profile fixtures to avoid unrelated changes. Update docs/ci-troubleshooting.md with symptom/cause/fix.
- Complexity: High. Token estimate: ~40k. Agent strategy: parallel upstream analysis and inspector tests, sequential pin integration.

### Phase 2.3: Make the first live session safe to inspect
- File changes: build_scripts/overlay/x13s.sh adds a live-only internal automount policy after inspecting actual GNOME/udisks behavior; scripts/build-iso-tacklebox.sh ensures policy survives customization; tests/test_x13s_profile.py and final artifact tests inspect applied policy. docs/X13S-SUPPORT.md receives exact digest/download, integrity steps, temporary external boot selection and result form.
- Verify policy does not disable necessary external root access. Test actual session rules and retain a manual desktop-mount warning: policy is not a guarantee against deliberate user writes. No installer instructions in this first live-only checklist.
- Complexity: Medium. Token estimate: ~20k. Agent strategy: independent policy tests and documentation, sequential artifact review.

### Phase 3.1: Record owner evidence and keep remaining gates visible
- File changes: docs/X13S-SUPPORT.md and issue3368 evidence links record the owner-supplied result; config/green-criteria.yaml and its consumers only change when their actual criteria are met. No exclusion to make the new profile appear green.
- Manual result includes artifact digest, device/firmware version, boot outcome, display/input/network observations and unchanged internal installation; redact serials/MACs before publishing. Stop at failed boot or unexpected internal mount. Recovery is power-off and removal of external media, then ordinary internal boot; no automatic firmware changes.
- Bootc/Fisherman installed lifecycle remains a later external-disk task: confirm actual backend, kernel-matched DTB on update/rollback and plain/passphrase-LUKS separately. Do not infer completion from live boot.
- Complexity: Medium. Token estimate: ~10k. Agent strategy: single coordinator with owner-provided observations; no unattended device execution.

## Testing Strategy

Use behavioral pytest/Bats for overlay and recipe effects, Go unit/fixture tests for builder staging, and final-artifact integration checks. Give loader selection and stale kernel/DTB rejection the most coverage because a plausible inventory can conceal unbootable media. Exercise compressed firmware, shared symlinks, missing payloads, built-in versus modular drivers, cross-architecture hosts, signed-byte preservation and argument propagation. Incident regressions follow the repository Falsification convention; no existing gate is disabled.

Artifact integration must inspect EFI architecture and chain, embedded DTB/CHID selection, kernel release, initramfs contents and effective arguments. Generic ARM64 QEMU tests can reject packaging errors but cannot establish SC8280XP boot success. Test automount suppression in the actual live desktop and verify no automatic installer runs. Normal repository formatting, lint and tests remain required.

Success metrics:
- Owner completes the external live test with exact artifact identity: Manual — captured in the implementation test plan.
- Existing internal installation remains usable and unchanged: Manual — captured in the implementation test plan. Automated live-policy tests cover no automatic mounting or installation but cannot substitute for the device observation.
- Every published support claim has matching artifact or physical evidence: behavioral tests reject incomplete evidence mappings; final publication review is Manual — captured in the implementation test plan.

Physical Wi-Fi, audio, brightness, suspend, camera, Secure Boot and installed update/rollback outcomes are deliberate remaining gaps until separately authorized tests provide results. Delivering inspected experimental media does not close those gates.

## Project References

Epic3368, W1 issue3377 and PR3389; Fedora F44 automatic-DTB proposal; RFC014 provenance boundaries. See research.md for exact source references.

## Token Management Strategy

Use independent package/source analysis and tests, then sequential integration. Reserve about 30k for overlay work, 40k for builder integration, 20k for live policy and 10k for owner evidence.

## Migration Notes

Coordinate source fields with primary TOML work; regenerate adapters. Preserve ARM64-only image admission and false ISO/QCOW2/LUKS flags until their gates are actually met. Upgrade the central builder pin after upstream review, retaining deadline and floor fixes.

## Performance Considerations

Avoid local multi-GB pulls in the constrained workspace. Use existing remote build capacity for artifacts; record compressed payload and media sizes. No performance claim or threshold is invented.


## Published loader audit update (2026-10-20)

The official Fedora updates candidate is available; package absence is no longer the blocker. The candidate loader uses systemd-stub 259.9-1.fc44. Its meaningful .linux payload and published stock kernel-core vmlinuz both have size 17,365,352 and SHA256 f838299696f91f0400de9e6b796d3d862f8e9eb2899101a913314150ce9550d6. Kernel-core, modules-core and loader metadata name the same kernel-7.2.11-200.fc44.src.rpm. This is candidate-package evidence, not evidence of the eventual root image.

The proposed live-only interface accepts separately pinned loader bytes without replacing kernel-core. Actual selected-stub GRUB/LoadFile2 boot, final module ABI, CHID choice, PE signature verification, redistribution materials and final ADSP initramfs ordering remain blocking checks. The complete inspected dracut108-8.fc44 package set lacks the named upstream ADSP hook and equivalent qcom_q6v5_pas/sc8280xp shell logic; final emitted initramfs remains decisive. No production consumer or admission changes are made.
