# RFC 015: Sealed UKI image mode

- **Status:** Draft — contract and investigation only; no implementation or support promotion
- **Issue:** [#3478](https://github.com/tuna-os/tunaOS/issues/3478)
- **Branch:** `rfc015-sealed-uki-mode`
- **Owner:** tuna-os maintainers
- **Related:** [#3474](https://github.com/tuna-os/tunaOS/issues/3474), [#3470](https://github.com/tuna-os/tunaOS/issues/3470), [#3445](https://github.com/tuna-os/tunaOS/pull/3445)
- **Historical context:** [#999](https://github.com/tuna-os/tunaOS/issues/999), [ADR 0003](../adr/0003-mkosi-co-build-poc.md)
- **Decision:** None. A maintainer must approve a prototype before it changes a build, installer, signature, or disk layout.

## Problem

TunaOS now ships bootc OCI images. Some images use composefs and
fs-verity, but no sealed-UKI mode exists in the repository. The word
“sealed” has several meanings here. A composefs root, a signed UKI, a
firmware-trusted signature, and an encrypted root have different failure and
recovery behavior.

This RFC defines the contract and evidence that a future mode would have to
satisfy. It does not claim that any current TunaOS image is a sealed-UKI image,
and it does not select a build or deployment backend.

## Scope and non-goals

This RFC covers:

- terminology for UKI, root-integrity, Secure Boot, and encryption assurances;
- an explicit, versioned image-mode contract;
- the TunaOS capability inventory and upstream constraints;
- a qualification plan for a disposable plain-install prototype; and
- fail-closed rules for unsupported combinations.

This RFC does **not**:

- upgrade the bootc pin or change fisherman;
- generate, enroll, rotate, or replace signature keys;
- change firmware Secure Boot state, shim policy, SBAT policy, or revocation data;
- change a partition table, ESP size, installer route, or production image;
- qualify encrypted installation, TPM enrollment, or TPM key reseal; or
- reopen the mkosi backend migration from #999.

## What “sealed” means

A future `sealed-uki` mode MUST report these assurances separately. A single
boolean such as the repository's current `SEALED=1` probe is insufficient.

| Assurance | Required meaning | Not implied by it |
|---|---|---|
| UKI byte integrity | The exact PE/COFF UKI bytes, including signed sections and the Authenticode certificate table, survive every inspection, copy, install, update, and rollback step. | Firmware trust, root integrity, or encryption. |
| UKI signature validity | The signature on those exact bytes verifies against the declared signer and policy. | That the firmware trusts the signer. |
| Firmware trust | The actual firmware → shim (if present) → bootloader → UKI chain accepts the payload with the intended Secure Boot state, including SBAT and revocation behavior. | That a signature merely exists or verifies with an arbitrary tool key. |
| Root integrity | The installed root has the declared fs-verity or dm-verity protection and the boot path checks the declared root identity. | A signed UKI or an encrypted volume. |
| Encryption | LUKS, passphrase recovery, TPM policy, and resealing behavior are separately qualified. | Any of the four assurances above. |

Composefs gives root integrity only when fs-verity passes its check.
An image can carry a valid UKI signature while its firmware chain remains
unqualified. This image has a signature but no Secure Boot qualification.

## Current TunaOS inventory

The following is the boundary a prototype must cross; it is not an inventory of
future support.

| Area | Current behavior | Consequence for `sealed-uki` |
|---|---|---|
| Image producer | The normal pipeline builds, rechunks, signs, and publishes OCI bootc images. TunaOS-owned build scripts rebuild a dracut initramfs, but there is no TunaOS-owned UKI assembly, UKI signing, or UKI artifact publication step in the current source tree. | A prototype needs an explicit producer and byte-identity handoff. It cannot infer a UKI from an OCI digest. |
| bootc version | [`image-versions.yaml`](../../image-versions.yaml) pins bootc at `v1.16.10`. The comment records an Arch `libselinux` constraint and treats that version as a ceiling. | Do not treat a release bump as an implementation. Reconcile the Arch constraint and test the selected version before any change. |
| Backend probe | [`scripts/lib/backend.sh`](../../scripts/lib/backend.sh) emits `BACKEND` and `SEALED`. `SEALED=1` means that `prepare-root.conf` enables composefs; it does not inspect UKI bytes, signatures, SBAT, cmdline sections, firmware trust, or ESP state. | The future contract needs a separate UKI/trust probe or an authenticated receipt. The existing value MUST NOT be renamed or reused as UKI support. |
| Disk gate | [`scripts/build-qcow2.sh`](../../scripts/build-qcow2.sh) installs with `bootc install to-disk`, selects ext4 when the root is detected as composefs-sealed, and otherwise uses the install configuration. [`scripts/corral-boot-gate.sh`](../../scripts/corral-boot-gate.sh) repeats the filesystem decision. | These gates prove a bootc disk can be built and booted. They do not prove a signed UKI, a Secure Boot chain, ESP overlap, or recovery after a failed UKI write. |
| GUI installer recipe | The recipe has `bootloader`, `composeFsBackend`, and `filesystem` fields. [`live-iso/common/src/installer-recipe-backend.sh`](../../live-iso/common/src/installer-recipe-backend.sh) derives those three values from image contents. [`customize-live.sh`](../../live-iso/common/src/customize-live.sh) rewrites the recipe at ISO build time. | A sealed-UKI capability and its negative cases are not represented. `systemd` plus `composeFsBackend=true` is not a signed-UKI declaration. |
| Fisherman path | The ISO E2E harness probes the image, writes a fisherman recipe, and runs the installer bundled by the selected frontend. The same file documents the current recipe's `to-filesystem` path. A separate generic LUKS test still invokes `bootc install to-disk` directly. | The installer must expose an explicit sealed-UKI capability. A plain bootc/fisherman success cannot be promoted to sealed-UKI support. |
| Secure Boot | [`docs/SECURE-BOOT.md`](../SECURE-BOOT.md) describes current variant-level Secure Boot behavior. It does not qualify a new UKI chain, SBAT/revocation behavior, or a sealed-image update path. | The mode needs artifact-specific trust evidence, including negative tests. Existing variant prose is not a substitute. |
| Lifecycle | [`bootc-lifecycle.yml`](../../.github/workflows/bootc-lifecycle.yml) checks published-image metadata, aliases, install configuration, and selected desktop contracts. It does not update, rebase, or roll back an installed deployment. | A sealed-UKI lifecycle must additionally prove UKI byte preservation, ESP capacity, loader selection, target-only boot, and recovery. |
| Browser/native media | Native and browser-produced ISO paths are separate delivery tracks; parity is tracked by #3470. | Qualification MUST identify both media producers. Passing a native ISO does not qualify a browser-produced ISO. |
| Historical DDI work | [`docs/mkosi-investigation.md`](../mkosi-investigation.md) and [ADR 0003](../adr/0003-mkosi-co-build-poc.md) distinguish bootc OCI output from the systemd-sysupdate + dm-verity + UKI DDI model. The DDI investigation did not produce a boot proof. | A DDI/UKI design is a separate deployment model, not a transparent second packaging of the current OCI image. |

The checked-in [`system_files/etc/bootc-installer/recipe.json`](../../system_files/etc/bootc-installer/recipe.json)
contains a `systemd`/composefs/xfs example, but the live customizer rewrites
these layout fields after the live customizer checks the final image. Neither
the example nor the rewriter carries signature, SBAT, UKI, ESP, or installer-capability evidence.

## Upstream status relevant to this proposal

These references constrain the design; none authorizes a TunaOS implementation.

- The TunaOS bootc pin is `v1.16.10`. The [bootc v1.17.1 release](https://github.com/bootc-dev/bootc/releases/tag/v1.17.1) contains composefs SSH-key and fs-verity-test changes; it is not a general sealed-UKI qualification.
- [bootc #2314](https://github.com/bootc-dev/bootc/pull/2314) merged systemd-repart support and a larger default ESP for composefs installs. [bootc #2551](https://github.com/bootc-dev/bootc/pull/2551) makes `--run-repart` explicit opt-in. These changes do not decide TunaOS's ESP budget or orchestration.
- [bootc #2132](https://github.com/bootc-dev/bootc/issues/2132) is specifically about ESP capacity for current, next, and rollback UKIs. It is not evidence that every sealed image has enough space. [bootc #2532](https://github.com/bootc-dev/bootc/pull/2532) remains open for a systemd 262/repart sizing follow-up.
- [bootc #2512](https://github.com/bootc-dev/bootc/pull/2512) remains open because systemd-boot can bypass shim when bootupd does not own the install. Its description separates the shim chain from a direct systemd-boot install. It also notes that its Secure Boot tests run with Secure Boot disabled.
- [fisherman #28](https://github.com/frostyard/fisherman/pull/28) records a signed-byte mutation caused by a UKI section read with `objcopy` without an output file. It also records that the suspected bootc mutation was a misattribution. A future verifier MUST use read-only inspection and hash the artifact before and after each handoff.
- The correction in [snosi #516](https://github.com/frostyard/snosi/issues/516#issuecomment-5207120626) keeps this issue separate from the fisherman defect. The two findings MUST NOT combine into an unsupported claim about a particular TunaOS build.

## Proposed versioned contract

The following is an illustrative `v1alpha1` contract, not a file consumed by
current TunaOS code. It makes every decision that can affect bootability or
trust explicit. Placeholder values are invalid in a qualification record.

```yaml
apiVersion: tunaos.org/image-mode/v1alpha1
kind: ImageModeContract
mode: sealed-uki
architecture: x86_64                 # x86_64 or aarch64; one exact target

# The deployment model is a design choice, not a consequence of the mode name.
deployment:
  model: bootc-composefs             # bootc-composefs, sysupdate-ddi, or co-build
  update_owner: bootc                 # bootc or systemd-sysupdate

boot:
  firmware: uefi
  loader: shim+systemd-boot           # or systemd-boot, explicitly
  secure_boot: required
  shim: required                      # required or absent, never inferred
  sbat: required
  uki:
    path: EFI/Linux/tunaos-<slot>.efi
    format: pe-coff
    sha256: <exact-uki-digest>
    signature:
      presence: required
      validity: required
      trust_policy: <reviewed-policy-id>
    kernel_parameters:
      source: signed-uki-cmdline
      values: [<ordered, exact, signed values>]
      sha256: <cmdline-digest>

root:
  filesystem: ext4                    # explicit; no xfs fallback for fs-verity
  integrity: fs-verity                # fs-verity or dm-verity, explicit
  identity: <root-digest-or-tree-id>

encryption:
  mode: none                           # `luks2` is a separate qualification
  qualification: excluded

installer:
  provider: fisherman
  capability_profile: sealed-uki-plain-v1
  source: offline                      # no network for the initial proof
  target: uefi
  mutation_policy: byte-preserving
  capabilities:
    plain_install: required
    target_only_boot: required
    update: required
    rollback: required
    recovery: required
    encrypted_install: not-qualified

provenance:
  source_revision: <source-commit>
  image_digest: <oci-or-ddi-digest>
  config_digest: <build-and-mode-config-digest>
  tool_versions:
    bootc: <exact-version>
    fisherman: <exact-revision>
    systemd: <exact-version>
    signing_verifier: <exact-version>
  media:
    native_digest: <native-media-digest>
    browser_digest: <browser-media-digest>
```

### Contract rules

1. `apiVersion`, `mode`, `architecture`, `deployment.model`, `boot.loader`,
   `boot.uki`, `root`, and `installer.capabilities` are required. Unknown
   versions, architectures, loaders, filesystems, integrity mechanisms, and
   capability profiles are hard failures.
2. `boot.uki.sha256` names the exact bytes that the producer signs and the
   installer installs. The verifier MUST compare hashes at build output, image
   extraction, inspection, installer handoff, ESP installation, update, and
   rollback. The verifier MUST reject any inspection command that can rewrite its
   input.
3. `boot.uki.kernel_parameters` is an ordered, signed input. An installer MUST
   reject a cmdline mutation after signature. A new UKI MUST carry a new
   signature and an independently recorded digest. Arbitrary host `--karg`
   injection is not compatible with this contract.
4. `signature.presence`, `signature.validity`, and firmware trust are separate
   evidence fields. A verifier MUST test the declared shim, SBAT, revocation,
   and firmware policy. A signature check on the host cannot prove the full chain.
5. `root.filesystem` and `root.integrity` are explicit. `SEALED=1`, a
   `composeFsBackend` flag, or a bootloader name MUST NOT silently select an
   incompatible filesystem or root-integrity mechanism.
6. An installer MUST reject a target, architecture, encryption mode, or
   capability it cannot prove. It MUST NOT fall back from sealed UKI to an
   unsealed bootc, GRUB, XFS, online-pull, or unsigned path.
7. `provenance` binds the evidence to exact image/UKI/media bytes, source,
   configuration, tool versions, and architecture. Native and browser media
   are distinct observations. Record one digest for each.
8. `encryption.mode: none` is the only initial proof target. Any encrypted
   record is invalid until passphrase recovery, TPM policy, and TPM reseal after
   update have their own evidence.

## Qualification evidence required for support

The following gates are deliberately future work. This RFC lists the
measurements. Do not treat current bootc or ISO gates as equivalent.

| Gate | Required proof | Evidence that must be retained | Failure behavior |
|---|---|---|---|
| Exact artifact | Build one disposable target from one exact image/UKI digest on one architecture. | Source revision, image digest, UKI digest, config digest, tool versions, architecture. | Reject the record if any identity is missing or inferred. |
| Byte preservation | Hash the UKI before and after read-only inspection, OCI/DDI extraction, installer staging, ESP copy, update, and rollback. | Ordered before/after hashes plus signature verification at each handoff. | Stop before boot or update; never repair by re-signing silently. |
| Secure Boot chain | Boot with the intended firmware state through the declared shim/loader chain. | Firmware mode, loader paths, signer identity, SBAT generation/policy, revocation state, verification logs. | Valid signature without firmware trust is a failed qualification. |
| Trust negatives | Test tampered bytes, wrong-key bytes, revoked/SBAT-invalid assets, unsigned assets, and an otherwise valid asset under the wrong firmware trust store. | The exact test artifact and the expected rejection point. | Fail closed before installing or booting; retain the working slot. |
| ESP capacity | Measure current + next + rollback UKIs, shim/loader assets, firmware assets, and update overlap for each architecture. | Partition layout, byte budget, free-space floor, and the exact payload sizes. | Reject insufficient space before modifying the working boot path. |
| Interrupted update | Interrupt a write at each boot-critical handoff and retry/reboot. | Pre/post ESP tree and boot result; old slot hash and bootability. | Preserve and boot the last known-good slot; no partial replacement. |
| Offline plain install | Run the actual shipped installer from native and browser-produced media with network unavailable. | Media digests, installer revision, recipe/contract, target-only boot logs, and screenshots or serial evidence. | No support if the installer needs an unrecorded fallback or network pull. |
| Target-only boot | Remove the build host, live media, and network dependency; boot the installed target alone. | Firmware boot entry, loader/UKI path, root-integrity verification, and desktop/service readiness. | Treat any host/live fallback as a failed install. |
| Update and rollback | Apply an update, boot it, intentionally fail a candidate, and roll back. | Current/next/rollback UKI hashes, boot selection, update logs, and post-rollback identity. | Keep the prior bootable slot; do not claim bootc lifecycle coverage alone. |
| Rescue | Exercise a bad update, revoked asset, failed write, and lost TPM state where applicable. | A tested rescue route and the exact remaining guarantees. | Stop promotion if recovery requires undocumented firmware or key operations. |
| Encryption | Repeat plain gates separately for passphrase recovery, TPM enrollment, and resealing across updates. | Encryption-specific evidence and failure recovery. | Out of scope for the initial plain prototype. |

## Architecture options and decision boundary

The contract is intentionally independent of the output model. The maintainer
must choose one model before implementation begins.

| Model | Reuses | Adds | Main unresolved risk |
|---|---|---|---|
| `bootc-composefs` | OCI build/publish and much of fisherman/bootc install. | UKI assembly/signing, loader policy, ESP accounting, and installer capability checks. | Existing backend and `SEALED` probe do not establish UKI or firmware trust. |
| `sysupdate-ddi` | systemd's native UKI, dm-verity, and sysupdate concepts. | A disk artifact, partition definitions, update stream, installer path, and new publication/provenance handling. | It is a different OS deployment model, not a second packaging of the current OCI root. |
| `co-build` | Current OCI delivery plus a separate sealed artifact. | Two artifact lifecycles, two install/update paths, and cross-artifact identity rules. | Doubled signing, testing, recovery, and browser/native parity surface. |

The recommended next action is a maintainer-reviewed choice between these
models, followed by one disposable **plain** target. The first prototype MUST
not change the production matrix, replace current artifacts, or include
LUKS/TPM qualification. This draft is not implementation approval.
Under [`RFC-PROCESS.md`](../../RFC-PROCESS.md), maintainers MUST record a
companion ADR when they approve and merge this contract/investigation scope.
That ADR records the scope and the non-implementation boundary. A later ADR
records the chosen architecture after the maintainer approves it.

## Sequencing

1. **Contract review:** approve or revise this vocabulary, schema version, and
   rejection behavior. Record the chosen model and first architecture.
2. **Capability audit:** pin the bootc, fisherman, systemd, and tool versions.
   Confirm that the installer keeps the exact signed bytes and cmdline.
   Reject any disk-layout or bootloader fallback.
3. **Disposable plain proof:** build one target. Measure the ESP budget. Run
   native and browser media through offline install and target-only boot.
4. **Negative and recovery proof:** exercise signature/trust failures,
   interrupted writes, update/rollback, and rescue before any promotion.
5. **Separate encryption qualification:** wait until the plain lifecycle passes.
   Then design and run passphrase, TPM enrollment, and TPM reseal tests.
6. **Admission decision:** use the variant/output-architecture admission rules
   in [`VARIANT-LIFECYCLE.md`](../../VARIANT-LIFECYCLE.md) and the completion
   gates in [`docs/IMAGE-FACTORY-GATE.md`](../IMAGE-FACTORY-GATE.md). No current
   support claim changes before those gates pass.

## Open decisions

- Which model owns updates and rollback: bootc/composefs,
  systemd-sysupdate/DDI, or a co-built pair?
- Which bootloader chain is supported first, and how is shim retained when the
  image contains it? The answer must account for SBAT and firmware revocations.
- Which exact root-integrity mechanism and filesystem are supported on each
  architecture?
- Which process assembles, signs, and inspects the UKI? Which tool must not
  change the input?
- Which installer capability covers a plain offline install? Which fields in the
  recipe describe target-only boot, updates, rollback, and recovery?
- What ESP minimum and update-overlap budget is required for each architecture?
- How do native and browser-produced media bind to the same source/config
  identity? How does the contract distinguish evidence for each artifact digest?
- Which later RFC/ADR decides encrypted installation, TPM loss, and TPM reseal?

Until these decisions and the evidence gates are complete, `sealed-uki` is a
proposal only. Current composefs/fs-verity behavior, the Grouper recipe work in
#3445, and the historical mkosi POC are inputs to the investigation, not
project-wide sealed-UKI qualification.
