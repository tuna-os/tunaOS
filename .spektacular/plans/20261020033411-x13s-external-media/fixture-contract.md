---
created_date: "2026-10-20"
document_status: draft
---

# Draft: selected Fedora loader handoff fixture

Status: design only, for review before any workflow or production-consumer change. This fixture proves an EFI handoff in an emulator; it cannot qualify X13s hardware, CHID selection, USB-C storage safety or the final live image.

## Reuse and scope

The repository already uses ubuntu-24.04-arm in arm64-ulimit-probe.yml and installs QEMU/firmware packages in iso-builder-parity.yml. Propose one bounded diagnostic job on ubuntu-24.04-arm with contents: read only, no GHCR login, no package write permission, no deployment and a 20-minute timeout. Prefer explicit reviewed dispatch; do not add triggers merely to work around absent dispatch access. Pin checkout/upload actions to repository-approved SHAs. Record runner image and installed tool versions. No new self-hosted runner or credential is needed.

Proposed runner dependencies are the official Ubuntu qemu-system-arm, qemu-efi-aarch64, mtools, dosfstools, cpio and C toolchain. Verify their exact package names/versions on the selected runner before implementation. Use TCG as the portable baseline and do not depend on privileged KVM access. No packages are installed in the booted source image.

## Frozen inputs

- Loader RPM kernel-uki-dtbloader-7.2.11-200.fc44.aarch64: 25038005 bytes, SHA256 5138287d052497fb9dc55e987433b364d61efed2748fe34446d3d7b0de55f00e. Exact EFI member and digest are in loader-contract.md.
- Fedora GRUB RPM grub2-efi-aa64 epoch1:2.12-66.fc44: 2235713 bytes, SHA256 e4bbcad68fc89a8998dd6b4cbffeaf992c3e34c92ed6b7877f4eddad781e9173.
- Fedora shim RPM shim-aa64-16.1-7.aarch64: 486495 bytes, SHA256 91344da2296b0a24b7ac8b8d41a50bf412235922c41b2a8ac783a1200ee262c0.
- Verify RPM signatures, retain source/license identities, safely extract only reviewed regular files, and record exact EFI hashes and architecture. Never modify signed bytes. Component digests are not a Secure Boot claim.
- Actual source-image kernel identity still comes from W1; the fixture uses the candidate published kernel pair and must not be presented as that image's test.

## Minimal payload and transport

Compile a tiny native ARM64 static PID1 from reviewed local C source. It mounts only proc/sysfs, checks a unique expected kernel argument, reports uname release and the observed device-tree compatible value, emits an unambiguous sentinel, and powers off. It has no installer, shell, network client, filesystem discovery or block-device write code. Verify ELF machine and static linkage. Produce a deterministic newc initrd containing only that executable and required empty directories. Record source, binary and initrd SHA256.

Construct a temporary FAT ESP image with mtools, without host mounts or block devices. Stage the byte-identical Fedora shim, GRUB, selected loader, external initrd and a minimal explicit GRUB configuration. Audit the actual GRUB prefix/config search path from its package before fixing paths. Use GRUB's Linux EFI command and initrd command, never a substitute EFI application or direct QEMU -kernel shortcut. Configure serial output on the emulator's PL011 console. No extra .osrel/.initrd/.profile sections, addons or credentials may cause the selected systemd-stub to create a competing initrd provider.

Launch QEMU virt with the reviewed ARM64 UEFI firmware and temporary writable VARS copy, read-only ESP transport, serial log, no graphical display, no network and no host disk passthrough. Record full argv and firmware hashes. Use the firmware's existing test configuration; no host firmware or security setting is changed. A timeout is a failure, never a passing missing-sentinel result.

## Required evidence and falsification

1. Positive boot must traverse the exact shim/GRUB/loader bytes, execute the external PID1, report the candidate kernel release and expected command-line nonce, and terminate cleanly. Serial text alone is not evidence of signature enforcement; trust state is recorded separately.
2. Removing external initrd must fail to emit the success sentinel. Changing/removing the expected argument must cause PID1 to report failure. These controls establish that handoff, rather than an embedded alternate payload, is tested.
3. Preflight rejects wrong architecture, changed component digests, mismatch between meaningful .linux bytes and selected kernel identity, unexpected embedded initrd-generation sections, and missing required files.
4. Preserve exact staged and post-build EFI hashes, QEMU/firmware identities, initrd digest, serial log, exit status and a structured report with hardware_boot=not_tested and secure_boot=not_tested unless separately verified.
5. Do not spoof an X13s SMBIOS identity in a generic virt machine: selecting the physical X13s DTB can make the emulated hardware invalid. CHID matching requires a separate controlled structural test and eventual owner observation. Generic fallback behavior and its observed DTB are recorded, not hidden.

## Source correspondence to establish

Actual loader .sdmagic/SBAT identifies systemd-stub 259.9-1.fc44. Upstream v259.9 initrd_register leaves an existing LoadFile2 provider intact when no internal initrd is supplied; embedded .osrel/.profile/PCR data or sidecars can change that condition. Actual loader lacks .osrel, .initrd and .profile. Upstream GRUB loader/efi/linux.c selects LoadFile2 for PE ImageVersion >=1, and this loader reports 259.9. Fedora's selected GRUB patch/source correspondence and runtime results remain outstanding.

- https://github.com/systemd/systemd/blob/v259.9/src/boot/initrd.c
- https://github.com/systemd/systemd/blob/v259.9/src/boot/stub.c
- https://github.com/rhboot/grub2/blob/master/grub-core/loader/efi/linux.c
- https://gitlab.com/cki-project/kernel-ark/-/merge_requests/4318
