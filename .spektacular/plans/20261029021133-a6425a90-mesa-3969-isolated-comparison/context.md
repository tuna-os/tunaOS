---
created_date: "2026-10-29"
document_status: final
closed_date: "2026-10-29"
---

# Context: 20261029021133-a6425a90-mesa-3969-isolated-comparison

## Current State Analysis

The isolated sibling worktree initially used712ab32057a2433752dc8f134ab11bb6a5b56ef2 and was rebased onto current main465296a14c31799e10dd4c2dd357ee486e34c82b after the first hosted source review. No lab runtime code existed at planning. Existing manual tests and native Albacore build arguments are available; the current image-input filter excludes genuine tests/manual code and a new dispatch workflow. This host has no KVM/DRI, Podman, QEMU or RPM build tools, and the owner has not authorized runtime. The old active ISO workflow and user checkout remain untouched.

The existing software generator preserves user fallback; an unforced greeter does not prove the affected condition. A lab-only before-display probe unit avoids missing control outcomes when GDM cannot start. Actual Cogl WINSYS renderer notes are grounded in Mutter49.4 source; downstream binary availability still needs later real observation.

## Per-Task Technical Notes

### Task: Refuse unapproved runs and unsafe inputs

- `tests/manual/mesa_3969.py:1` — new standard-library authority/provenance/transport/owned-state/evidence core. Fixed INPUTS and LabError are shared; CLI commands inputs, admit, producer, init-root, cleanup-child, cleanup, fetch-inputs and pack-evidence. Existing image filters and production adapters stay unchanged.
- `tests/test_mesa_3969_safety.py:1` — new behavioral tests for exact-head/event/first-attempt/API identity, artifact substitutions and archive/path/size/tamper boundaries, mask/private-key filtering and owned cleanup that preserves outside state. No tests of source text or copied constants.

Agent strategy: integration owner writes this core and the workflow while two independent implementation slices use the locked contracts below. No intermediate tests, builds, linters or formatters; integrate before verification.

Local admission requires GITHUB_ACTIONS=true, official server/API/repository/id, workflow_dispatch, run_attempt1, valid nonzero run ID, exact40-hex checkout/context/REVIEWED_HEAD/MESA_3969_APPROVED_HEAD equality and LAB_CONFIRM=RUN_MESA_3969_ONCE. Before effects, live API must confirm official repository id1029250013, current in-progress manual run/head/attempt/workflow/path and no earlier run for that workflow/head, including cancelled attempts. Unknown/overflow/inconsistent metadata refuses. No owner variable/environment/secret is created.

Admission JSON fields: repository_id, repository, head_sha, run_id, run_attempt, workflow_id. Producer adds job_id for the unique current build job named Build signed Mesa pair. Manifest schema_version1/kindmesa3969-inputs binds this producer plus exact INPUTS, baseline raw/lab image IDs, buildroot identity and metadata, signer fingerprint, probe identity, both arm package records and every transferred file's bytes/SHA256. Unknown keys/types/ranges and incomplete sets refuse.

INPUTS contains baseline_parent, srpm_url, srpm_sha256, source_rpm, patch_url, patch_sha256 and helper_commit. Values are the exact approved inputs in working-context.md; no user-selectable source/version/URL. Package records share name, epoch, version, release, arch, source_rpm, header_sha256, path, sha256 and bytes; binary arm records require exact source_rpm and a real64-hex header digest. Non-Mesa inventory records may retain absent source/header values where RPM does so, but must remain unchanged.

Transfer allowlist: manifest.json; baseline.oci.tar; public-key.asc; baseline-inventory.json; buildroot-inventory.json; buildroot-macros.txt; toolchain.txt; build-report.json; and rpms/control/*.rpm or rpms/candidate/*.rpm with strict safe basenames. All non-manifest members must be declared exactly once. Authenticate server artifact ID/name/current run/head/first attempt, successful producer job and independent upload digest before reading the bounded manifest, extraction or image load. API artifact metadata alone is not the manifest's authority. Strip Authorization on signed download redirects. Cap archive24GiB, unpacked32GiB, member count2048 and JSON4MiB. Reject traversal, symlinks/nonregular entries, encryption, duplicates, undeclared/missing files, wrong sizes and hashes; stage into an empty owned destination.

Owned root must be the exact nonsymlink child RUNNER_TEMP/mesa-3969-<run_id>-<build|runtime>, mode0700 and marked with expected repo/run/head/role/UID. Cleanup verifies marker and safe ancestry, never global prune. cleanup-child only removes the fixed work child while keeping sealed transfer/evidence for later upload; final cleanup removes the complete root. Cleanup remains usable after cancellation without live runtime admission. sanitize_text removes add-mask command lines and redacts their values across selected logs; private-key content refuses publication. Evidence is a separate fixed selected-text/PNG allowlist capped32MiB, never a recursive raw-state upload.

### Task: Prepare the coherent signed Mesa pair

- `tests/manual/mesa-3969-build.sh:1` — new shell build/sign/freeze entry, default admission before effects and side-effect-free --plan. Use a single direct unchanged Containerfile.el10 tuna build from an exact reviewed git archive with canonical scripts/config.py generate --root materialization. Do not invoke or patch-copy scripts/build-image-inner.sh:217-232: it unconditionally retries and can run buildah rm -a. Mirror its reviewed build args from75-120, including pinned image/tool refs, fixed parent and actual build-script hash; record exact argument identities. Install native build dependencies once, capture root/macros/compiler inventories and commit one immutable labelled build image. Run complete original/candidate builds with network disabled; preserve vendor flags/checks. Candidate adds Patch1002 after the original11/12/13/14/1001 chain under existing autosetup-p1. No skip-check, nosignature, nodeps shortcut, retries or production credentials.
- `tests/manual/mesa_3969_packages.py:1` — new RPM query/spec/closure/install-inventory logic, using shared INPUTS/LabError and validate_package_record. Select baseline-installed closure by exact SOURCERPM, compare full output name/epoch/version/release/arch/source sets, and require same-NEVRA immutable header identity per installed arm. Validate RPM's SHA256HEADER tag before use; RPM documents it since4.14 (https://rpm.org/docs/4.20.x/manual/signatures_digests.html). The header covers payload digest; whole transferred RPM SHA256 and isolated signature verification remain separate.
- `tests/test_mesa_3969_packages.py:1` — new behavior tests for spec/patch drift, missing/extra/mixed package sets, unrelated inventory changes and same-NEVRA wrong-arm headers. Minimal data fixtures, no actual package build/key generation and no source-text assertions.

Agent strategy: one build-slice agent owns these three files, reading actual Justfile/factory references before commands. No checks or execution mid-flight; parent integrates and verifies.

One expiring rsa3072 signing key serves both arms, only in owned work. Use an isolated RPMdb containing only its exported public key and require actual signature OK. Freeze a shared lab baseline with public trust and identical probe/policy/logging instrumentation before deriving either arm; no private key enters build context, image or transfer. Keep the production software generator byte-identical. The guest slice supplies mesa_3969_guest.py and mesa-3969-probe.service; copy those and the pinned C probe compiled with existing flags into a minimal context, not the private work root. GDM gets the same explicit LIBGL_ALWAYS_SOFTWARE=1 and logging-only COGL_DEBUG=winsys in both arms; preserve the original user software policy and add only logging diagnostics, not a global swrast override.

Emit transfer and sanitized evidence under the owned root and GITHUB_OUTPUT transfer_path/evidence_path after admission. A trap removes temporary keys/work and owned containers/tags while preserving sealed outputs for upload; final workflow cleanup removes the root. Complete binary output sets are signed/transferred; selected installed closure alone is installed by one offline local RPM replacement transaction with dependency checks. Reject baseline source/version drift, mismatched header identities or any unrelated package change. Record generated SRPM hashes, no production publishing.

### Task: Compare real software-rendered desktop behavior

- `tests/manual/mesa-3969-guest.sh:1` — new default-refusing sequential runtime entry, side-effect-free --plan. Fetch/verify exact same-run inputs through the core before privileged image load. Revalidate package/signature identities, derive control/candidate from the same loaded baseline, and run the pinned corral-boot-gate.sh once per arm with the real GDM check. HOME/XDG per arm stay inside owned work. Preserve its deletion,900s boot/default GDM deadlines and real keyboard transitions; do not set its optional EGL probe path a second time. Observe while it runs, stop bounded observer children, preserve real wrapper exit and sanitize only selected evidence. Never upload raw corral/result.json, SSH keys, disks or ISOs.
- `tests/manual/mesa_3969_guest.py:1` — new probe/observe/compare data entry points. Probe mode uses the pinned C binary, selects the actual virtio DRM device and runs exactly clean/software/override/both with original20s timeout/5s kill bounds, recording normalized signal exits and bounded stdout/stderr. Observe mode adds only actual GL_RENDERER/process/session records to the existing greeter evidence, not a competing collector. Compare mode validates control reproduction, candidate crash absence, installed arm identity, unchanged software policy and real visible Wayland transitions.
- `tests/manual/mesa-3969-probe.service:1` — lab-only oneshot before display-manager, after DRM/udev and Plymouth release; record outcomes even when control GDM fails. Bounded collection is not a repair gate; the host comparator owns failure interpretation. One VM per arm, no pause, retry or cleanup shim.
- `tests/test_mesa_3969_guest.py:1` — new evidence/verdict behavior tests: wrong/reused PID, UID/boot/start-time mismatch, stale journal, fake environment-only success, hardware renderer, missing UI transitions, absent probe record, candidate crash and correctly classified missing-device outcomes.

Agent strategy: one guest-slice agent owns these four files, reusing the actual pinned helper sources unchanged. No checks, guests or key generation mid-flight; parent integrates and verifies.

GL_RENDERER evidence must come from actual gnome-shell Cogl WINSYS messages, not eglinfo or requested flags. Bind trusted journal metadata (_BOOT_ID,_PID,_UID,_EXE,monotonic time) to a held live process identity/start time, actual allowed renderer environment and the greeter selected by the existing collector or the real logged-in user Wayland session. Require software evidence for greeter and user; no inferred flag success. The current generator only exports LIBGL_ALWAYS_SOFTWARE, not MESA_LOADER_DRIVER_OVERRIDE. Keep all existing software/security policy; require SELinux enforcing and Wayland. Control expected probe statuses0/139/139/139 remain visible; a control gate failure is a negative observation, never silently discarded. Candidate clean must initialize; candidate other cases may be explicitly unexercised3/4, not called EGL success, only accompanied by complete positive software-rendered UI proof. Candidate crash or missing required proof rejects repair. This is a lab verdict, not epic completion.

### Task: Offer one bounded manual workflow

- `.github/workflows/mesa-3969-compare.yml:1` — new dispatch-only workflow with reviewed_head and confirmation inputs. Always-run cheap admission fails without exact owner activation. Build job needs admission and uses existing8CPU/80GB build-amd64 profile,180min; sequential runtime job needs successful build and uses KVM-capable Ubuntu24.04,60min. Read-only contents/actions, cancel-in-progressfalse, no reusable/PR/push/schedule trigger, retries or publishing permission. Pin action versions using current repo patterns. Upload exact transfer root with1day retention and0compression; consumer uses artifact ID/digest outputs, not latest/name discovery. Evidence always uploads only sanitized output, with final marker-bound cleanup even on failure/cancel. Do not create vars, environments or secrets.

Agent strategy: integration owner, after shared interfaces are locked; can author independently of implementation. No workflow dispatch. Existing image-admission filter remains untouched, and final changed-path proof precedes publication.

### Task: Verify and publish the source-only candidate

- `docs/TESTING.md:34` — add operator instructions and source/runtime boundary after actual source smoke proves commands. State exact activation/one-attempt/resource/artifact limits and held runtime; no ISO/config qualification claim.
- `docs/ci-troubleshooting.md:13` — add only observed source safety diagnoses and concrete remedies, not hypothetical repaired Mesa evidence.
- `.spektacular/changelog/20261029021133-a6425a90-mesa-3969-isolated-comparison.md:1` — required feature change record through the implementation workflow after smoke proof.
- `.spektacular/changelog/tunaos/20261029021133-a6425a90-mesa-3969-isolated-comparison.md:1` — repository-specific change record if required by the CLI's existing pattern; no runtime claim.

Agent strategy: integration owner runs affected suites once after agents finish, real default-refusal/integrity/owned-cleanup source smokes and mandatory just fix/check. Respect frozen existing verification assets; fix implementation, not gates. Use the CLI implementation test plan for later manual approval/runtime obligations. Check main/open work before publishing the isolated branch/draft PR, observe ordinary CI and exact tested source/merge identity, no dispatch or merge. Do not count source CI as repaired GDM, the eight-image campaign, encrypted install or either epic.

## Testing Strategy

- Safety core: pure authoritative-metadata decisions plus real CLI default refusals, bounded archive extraction/tamper cases and filesystem cleanup effects; injected API fixtures test rejection, not a mocked successful experiment.
- Packages: minimal RPM metadata/spec fixtures establish exact source/closure/header behavior, especially same-NEVRA wrong-arm substitution and unrelated package changes. No key or build occurs.
- Guest evidence: realistic journal/process/session/probe/transition fixtures establish identity/time/software and crash/missing-device verdict boundaries; no environment-only assertion substitutes actual renderer evidence.
- Integration: execute the real source-only refusal/integrity/owned-state paths, then affected suites and just fix/check after all edits finish. Preserve frozen existing tests and default routing.
- Publication: observe actual ordinary source CI and exact head/merge identity; source CI cannot supply the held manual runtime metric. The implementation test plan must retain owner exact-head approval and real paired renderer/UI report review as unexecuted manual items.

## Project References

- Registered tunaos root: /home/ubuntu/dev/tuna-os/tunaos-mesa-3969-lab-source; all code changes belong here. Registered docs repo is the public metrics site and needs no change.
- Final specification 20261029021133-a6425a90-mesa-3969-isolated-comparison and the loaded effect/evidence/cleanup/gate/tool/test conventions.
- Prior artifact-transport plan20261020002748-iso-artifact-transport-adapter, primary RPM signature/digest documentation and Mutter49.4 sources in research.md.
- Justfile:56-143; .github/scripts/tuna-pr-build-inputs.sh:5-14; pinned #3974 helper source and native package-factory references recorded in research.md.
- No design documents are referenced.

## Execution Strategy

Two independently owned implementation slices author package preparation and guest observation against the fixed shared contracts. One integration owner writes safety/provenance, orchestration and final verification/documentation. Slices must not run builds, tests, linters or formatters mid-flight. No overlapping edits; integration and complete verification happen once their source is ready.

## Migration Notes

Only the separately approved isolated schema3-to4 planning-settings migration was needed and is already complete. No production caller, existing test asset, image filter, key, setting, R2 object or publication lane is migrated by this lab. The source workflow remains unavailable for runtime until separately approved merge/registration and exact-head activation.

## Performance Considerations

Use one dependency-complete immutable buildroot and one baseline, no duplicate production factory or repeated dependency resolution. Build caps remain8CPU/80GB/180min; sequential one-VM-per-arm runtime stays60min with original probe/helper deadlines. Transfer caps24GiB archive/32GiB unpacked and1day retention; evidence32MiB. These are limits, not measured use or runtime approval. Actual sizes, duration and runner availability remain unmeasured.

## Latest owner instruction: CI-only verification

No local builds, tests, smokes, linters or formatters. Author source, publish a review candidate and run source verification in hosted CI. This supersedes earlier local command wording in these historical technical notes. Preserve the frozen existing Test/lint workflows. The existing Test workflow discovers tests/manual/test_mesa_3969_source_smoke.py as a real CLI integration test in hosted CI and supplies ordinary pytest, lint and formatting validation. No separate PR workflow or edit to existing Test/lint workflows, fork-classification scripts, tests or image filters is needed. No Mesa package build, key, guest or runtime dispatch is authorized.

## Integrated source boundaries

- `tests/manual/test_mesa_3969_source_smoke.py:1` — CI-only real CLI refusal/integrity/owned-state proof; credential-free and fail-closed tool sentinels prevent accidental runtime.
- Existing Test pytest discovery runs the real source CLI smoke directly; no new PR workflow, image admission or edit to frozen verification assets.
- Package replacement additionally requires root inside an owned lab container with the embedded exact producer identity, preventing accidental host/unrelated-container installation.
- Preserve diagnostic core policy; no added core-dump suppression. Sanitization decodes JSON strings before secret/private-key filtering.

## Observed hosted verification and remaining holds

Initial source head7148c31d848ee4399bc91a2e71d10a06b31c230e was exercised as mergefeb9d9b0f7355320a6966eb12f31784f54ea6bb8 against base255dc6b462664fdfba8cd5ffa75e4bfe3c5f8b57. Hosted source smoke40826993325 passed real default refusals, synthetic archive integrity/tamper refusal and marker-bound cleanup. All363 new Mesa pytest cases passed in Test40826993499; lint, Just Fix and prose also passed. Full CI was not green.

The new-workflow inventory/classification failures are addressed by canonical docs/CI_SPEC.md generation and moving the same real smoke into ordinary pytest discovery, not by modifying scripts/fork-simulation.py (which would admit an unapproved image matrix). These integration changes need CI at the new source head. The existing runner-pin boundary assertion reads unchanged reusable-build-image.yml; package-catalog failures report a stale Containerfile.debian source observation. Do not weaken frozen tests, refresh authenticated observations blindly, rerun unchanged failures or claim these are Mesa runtime results. #4052 repairs a different guest-check fixture and is not a fix for these failures.

Local execution since the CI-only instruction has been source authoring, planning metadata, Git publication metadata and the canonical documentation generator without --check; no local build, test, smoke, linter, formatter or compile/import check. No lab key, package build, guest, runtime dispatch, merge, activation variable, production publication or R2 change is authorized.
