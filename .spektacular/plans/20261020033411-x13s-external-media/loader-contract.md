---
created_date: "2026-10-20"
document_status: draft
---

# Draft: immutable loader input for X13s live media

Status: proposed for review. No production consumer, RPM transaction, installed-kernel replacement or admission change is implemented.

## Chosen investigation path

Retain the stock Fedora kernel-core and matching modules in the root image. Supply the published, same-release kernel-uki-dtbloader EFI payload as a separate immutable input to an explicitly live-only native builder mode. The payload remains outside /boot/EFI/Linux in the source image: it is an incomplete UKI, not a sealed/full UKI with its own initramfs. Installed support remains blocked on a separate lifecycle design.

## Independently reviewed inputs

- Profile fixed to bonito:gnome-x13s, linux/arm64 and live-only mode. Other targets reject the input.
- Immutable source image digest and observed kernel release from that image, including the final prepared initramfs's module release.
- Published RPM NEVRA, official repository origin, repository-metadata digest, RPM byte length/SHA256 and approved Fedora signer fingerprint. Do not resolve latest at build time.
- Exact RPM member path and extracted EFI length/SHA256. No scriptlets, arbitrary archive paths, symlinks or full package installation.
- Expected board compatible string lenovo,thinkpad-x13s and reviewed CHID-selection evidence. Presence of .hwids alone is insufficient.
- Exact shim/GRUB ARM64 inputs and configuration, with component digest and trust evidence. Preserve signed bytes; record Secure Boot as untested.

## Verification order

1. Verify the selected RPM digest/length against independent reviewed input, then verify its RPM signature with the approved Fedora key. The local audit validates the detached RPM header signature with GnuPG using Fedora 44 fingerprint 36F612DCF27F7D1A48A835E4DBFCF71C6D9F90A6 and matches its signed payload SHA256 to the compressed payload. Public-key trust is bootstrapped from Fedora's HTTPS security page and keyring, not an independently provisioned key. Native rpmkeys and EFI Authenticode verification remain outstanding.
2. Inspect package metadata and retain the package's applicable license notices and source-package identity in the artifact materials. A catalog license string is not a redistribution-compliance verdict.
3. Extract only the explicitly named regular-file payload without running package content. Reject duplicate names, unexpected size/type, traversal, decompression overrun and changed EFI bytes.
4. Require ARM64 PE structure, exact .uname match to retained kernel and initramfs module release, and the correct root compatible property in an embedded DTB. A release string alone does not prove byte equality or module ABI compatibility: record the .linux meaningful payload hash, retained kernel hash and exact kernel/modules source build identities, then prove their relationship. Validate the CHID mapping/selection separately; a substring match cannot pass.
5. Stage a byte-identical shim/GRUB/loader chain and an external initramfs. GRUB must supply the selected image's arguments and the final rebuilt initramfs through the supported Linux EFI handoff. Do not use generic chainloader semantics and assume initrd delivery.
6. Inspect the emitted ISO/ESP and exercise the actual selected Fedora systemd-stub 259.9-1.fc44 payload under ARM64 firmware to verify the GRUB handoff, external initramfs and command line. A generic EFI placeholder fixture cannot satisfy this criterion. This is packaging evidence only. Physical CHID selection and X13s boot remain owner tests.
7. Require actual final initramfs evidence that board firmware and ADSP pre-udev reset ordering precede any external root mount. If ordering is absent or unproven, do not offer the artifact for USB-C testing. A permanent remoteproc blacklist is not an accepted substitute.
8. Verify live-only no-install/no-internal-automount policy, then attach the exact receipt and bounded owner checklist. No installed-image or upgrade path inherits this loader input implicitly.

## Measured candidate, not approved production input

Official Fedora 44 ARM64 updates primary metadata SHA256: 735279e1d2ab7b3f57bb2b6a8d31c07b0961997d9feb65d2a5e8e92466aef9f7.

RPM: kernel-uki-dtbloader-7.2.11-200.fc44.aarch64, 25038005 bytes, SHA256 5138287d052497fb9dc55e987433b364d61efed2748fe34446d3d7b0de55f00e.

Member: lib/modules/7.2.11-200.fc44.aarch64/vmlinuz-dtbloader.efi, 22371176 bytes, SHA256 040491c473a209b70f6e75bee5f1850bec54b175ceb8f35b64bf102b1be738d2. Observed PE machine 0xaa64; .uname matches 7.2.11-200.fc44.aarch64; one .dtbauto root compatible is exactly lenovo,thinkpad-x13s plus qcom,sc8280xp. CHID selection, PE signer verification and boot were not performed.

The RPM conflicts with kernel-core at the same version. This path avoids invoking that transaction. Alternate installed design B requires an explicit reviewed package swap, canonical vmlinuz/HMAC adaptation and complete bootc deployment/update/rollback tests; it is not part of the first live artifact.

Published dracut108-8.fc44 ARM64 main and seven split packages were inspected by checksum and CPIO contents. Their shell payloads contain neither the named upstream modules nor qcom_q6v5_pas/sc8280xp logic. This finding covers that package set only. Final image and rebuilt-initramfs checks remain decisive.

## Test contract

Current local observer tests cover ARM64-only parsing, bounded headers/payloads, section overlap, repeated DTB sections, exact root compatible properties, nested false matches, malformed DTBs and explicit unverified trust/boot fields. They also parsed the candidate RPM's actual EFI bytes successfully. They do not satisfy the future input consumer's acceptance tests.

Before consumer integration add negative cases for every independently selected identity, kernel/initramfs mismatch, untrusted signer, missing trust evidence, wrong RPM member/type, duplicate archive member, modified signed bytes, missing chain dependency, malformed CHID mapping and unsupported target. Add a mocked transaction assertion that no package manager is called. Build fixtures must prove the input reaches only the live ARM64 profile and is excluded from installed targets. Selected-stub boot tests must observe the actual external initrd and command line, and fail without them. The owner test is the only physical proof.

## Sources

- https://dl.fedoraproject.org/pub/fedora/linux/updates/44/Everything/aarch64/repodata/repomd.xml
- https://gitlab.com/cki-project/kernel-ark/-/merge_requests/4318
- https://github.com/dracut-ng/dracut/pull/2302
- https://github.com/redhat-plumbers/dracut-fedora/pull/89
- https://github.com/bootc-dev/bootc/blob/de7ae55a1c859df999a8d9ccc5eee32372f4c6f0/crates/lib/src/kernel.rs
- https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
- https://devicetree-specification.readthedocs.io/en/stable/flattened-format.html
