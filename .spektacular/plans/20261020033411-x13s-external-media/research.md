---
created_date: "2026-10-20"
document_status: draft
---

# Research: 20261020033411-x13s-external-media

## Alternatives considered and rejected
- Package-only enablement: Fedora lists the required firmware, but the pinned native builder stages host EFI bytes and lacks the selected DTB-loader path. Firmware presence cannot establish a bootable artifact.
- Fixed ESP DTB copy: fails kernel/DTB lifecycle continuity and the W1 decision in #3377; reject for installed deployments.
- Treat browser shim/GRUB support as native support: distinct code paths. Browser provenance work cannot establish native boot-chain behavior.

## Chosen approach — evidence
Retain Fedora stock kernel plus packaged board firmware. Implement and verify the W1-selected shim/GRUB/Fedora kernel-uki-dtbloader payload payload with image-architecture matching, kernel-matched DTB selection and final artifact inspection before experimental live delivery. Installed update/rollback remains a separate physical gate. Fedora F44 automatic-DTB proposal describes embedded DTBs and CHID selection, but actual installed package behavior still requires artifact inspection.

## Files examined
- tunaos:build_scripts/overlay/x13s.sh — W1 inventory only, no firmware installation or hardware success.
- tunaos:tests/test_x13s_profile.py (PR3389) — shell execution with fixture root, compressed firmware and symlink cases.
- tunaos:scripts/build-iso-tacklebox.sh:198 — recipe currently supplies console=ttyS0 only.
- tunaos:image-versions.yaml — native builder pin ae93e9b5bacef49746cb1b08dc805c3149d7c9c8.
- tunaos:build_scripts/overlay/t2.sh:128 — existing reproducible non-hostonly dracut pattern.
- tacklebox@ae93e9b:internal/install/live.go:488 — host-only EFI probe, x64 first, image not probed; :514 extracts module-tree vmlinuz/initramfs.
- tacklebox@d36fdb84:internal/install/bootchain.go — image-architecture-aware systemd-boot staging, not the native Fedora shim/GRUB path.
- tacklebox@d36fdb84:internal/install/bootloader.go — BLS without DTB field.
- tacklebox@d36fdb84:internal/recipe/recipe.go — global kargs, no hardware loader selection.
- fisherman@3c040fc4:fisherman/internal/install/systemdboot.go — x64 fallback, only relevant when systemd/ZFS backend is selected; actual Bonito GRUB lifecycle needs separate verification.

## External references
- https://gitlab.com/cki-project/kernel-ark/-/merge_requests/4318 — proposal uses kernel-uki-dtbloader with exact-version kernel-core conflict; published availability remains unverified.
- https://github.com/dracut-ng/dracut/pull/2302 — merged pre-udev ADSP ordering fix explicitly covers sc8280xp; verify actual Fedora package and emitted initramfs.
- https://fedoraproject.org/wiki/Snapdragon_WoA_Laptop_Install — USB-C ADSP restart can detach mounted root; current guide is not proof the exact image has the fix.

- https://github.com/tuna-os/tunaOS/issues/3368 — scope and physical evidence gates.
- https://github.com/tuna-os/tunaOS/issues/3377 — W1 parent observations and loader decision.
- https://packages.fedoraproject.org/pkgs/linux-firmware/qcom-firmware/fedora-44.html — 21BX DSP/topology and a660 files, dependencies and licenses; package catalog, not built-image evidence.
- https://fedoraproject.org/wiki/Changes/Automatic_DTB_selection_for_aarch64_EFI_systems — Fedora Fedora kernel-uki-dtbloader payload design.
- https://raw.githubusercontent.com/torvalds/linux/master/drivers/base/firmware_loader/main.c — exact firmware names and supported .xz/.zst suffixes.

## Prior plans / specs consulted
- 20260924185724-68c5afaf-tacklebox-commit-deadline — preserve central pin and ancestor fixes when upgrading builder.
- 20261019211556-iso-media-provenance — exact media identity, independent producer context and no synthetic qualification.
- 20261020002748-iso-artifact-transport-adapter — observed archive integrity differs from authenticated production evidence.
- ADR0002 browser ISO builder — preserve browser delivery direction; no new permanent artifact stream or service.

## Open assumptions
Actual Fedora loader PE layout and CHID entries must be measured before coding loader selection. Determine GRUB installed backend and update/rollback ownership before installation support. Missing proof blocks the dependent step, not unrelated firmware tests. External-media automount suppression must be tested against the actual desktop/session policy.

## Drafting assumptions

### Existing native inspection path (architecture)
- **Decision**: Extend the existing experimental native build path while preserving the long-term browser delivery direction.
- **Rationale**: It permits bounded payload inspection without adding a permanent artifact stream or waiting for unrelated browser provenance work.
- **Rejected**: Pin-only enablement cannot supply native GRUB; package-only work cannot produce bootable media; browser API conformance is not physical evidence.

### Relevant conventions (architecture)
- **Decision**: Apply main, generated-config, central-pin, behavioral-test, evidence, destructive-path and normal-check conventions.
- **Rationale**: These directly govern the changed build, payload and owner-test surfaces.
- **Rejected**: Unrelated metrics-site implementation rules; that registered repository is not modified in this phase.

## Rehydration cues
Read AGENTS.md, RFC process and pinned Spektacular plan skill. Refresh #3368/#3377/#3389, current main and the exact builder pin. Read this spec and plan through Spektacular CLI. Recheck native and browser paths separately. Coordinate matrix edits with the TOML migration and avoid browser evidence API files owned by parallel work.


## Published loader audit update (2026-10-20)

The official Fedora updates candidate is available; package absence is no longer the blocker. The candidate loader uses systemd-stub 259.9-1.fc44. Its meaningful .linux payload and published stock kernel-core vmlinuz both have size 17,365,352 and SHA256 f838299696f91f0400de9e6b796d3d862f8e9eb2899101a913314150ce9550d6. Kernel-core, modules-core and loader metadata name the same kernel-7.2.11-200.fc44.src.rpm. This is candidate-package evidence, not evidence of the eventual root image.

The proposed live-only interface accepts separately pinned loader bytes without replacing kernel-core. Actual selected-stub GRUB/LoadFile2 boot, final module ABI, CHID choice, PE signature verification, redistribution materials and final ADSP initramfs ordering remain blocking checks. The complete inspected dracut108-8.fc44 package set lacks the named upstream ADSP hook and equivalent qcom_q6v5_pas/sc8280xp shell logic; final emitted initramfs remains decisive. No production consumer or admission changes are made.
