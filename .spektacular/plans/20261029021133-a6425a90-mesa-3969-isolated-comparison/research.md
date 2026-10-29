---
created_date: "2026-10-29"
document_status: final
closed_date: "2026-10-29"
---

# Research: 20261029021133-a6425a90-mesa-3969-isolated-comparison

## Alternatives considered and rejected

- Reinitializing mock twice does not freeze dependency state. The Alma config pins its bootstrap image, but its repository URLs move (reference: mock/alma10-ci.cfg:11-82). The factory also needs its own signed candidate policy. Do not copy that production lane into this lab. Prepare dependencies once in an owned container, commit its immutable image ID, and run both complete builds from that ID with networking disabled.
- A separate baseline per arm could move packages between builds. Build one Albacore tuna baseline with the supported positional chain_base_image argument (tunaos:Justfile:56,102-143), then derive both arms from that same measured image. Exporting BASE_IMAGE alone is not the supported override. Source-only resolve-flavor.sh albacore tuna 1 returned Containerfile.el10, DESKTOP_FLAVOR=tuna, no parent or overlays.
- DNF online reinstall can change unrelated packages; unverified --offline recipes are not accepted. Use one local RPM replacement transaction, with dependency checks enabled and no network, after isolated signature checks. Select every baseline-installed output by exact SOURCERPM, not name prefix. Full before/after package inventories must match except the replaced Mesa payloads and the explicit lab public-key record.
- EGL noncrash or an unforced GDM pass is not a repair. Candidate enumeration can remove matching DRM devices. Keep exit3/4 separate from successful initialize, preserve all four controls, require a reproduced negative control and actual software-rendered visible GDM transitions.
- Do not inject a loader shim, weaken security policy or change helper deadlines for renderer proof. Upstream Mutter49.4 has an existing logging-only route: COGL_DEBUG=winsys emits GL_RENDERER from the actual compositor context. Its trace fallback is g_message, not a debug-build-only stub.

## Chosen approach — evidence

Use a test-only manual harness under tests/manual/ plus one standalone workflow_dispatch-only workflow. The unchanged Tuna image-input filter includes scripts/** but not tests/manual/** or a new standalone manual workflow (tunaos:.github/scripts/tuna-pr-build-inputs.sh:5-14). This is a manual test, not a relocated production change.

The package factory already uses native Alma DNF builddep and captures RPM/compiler inventories (reference:scripts/run-alma-rpm.sh:71-90). Its temporary signer uses one expiring key, an isolated RPM keyring and rpmsign, never the host keyring (reference:scripts/candidate-rpm-repository.py:36-110). Reuse those patterns, not their production publisher or credentials. Freeze the dependency-complete build container once; preserve vendor macros and capture both buildroot identities. Keep the exact original SRPM/spec patches; candidate adds the entire agreed upstream patch through the existing autosetup chain.

Reuse #3974 source at0172a317c6213a9bbf8650913d5abf8880d8170b: corral-boot-gate.sh owns VM lifecycle, gdm-login-gate.sh owns real keyboard/login/lock/unlock, greeter-graphics-evidence.sh owns greeter selection, and repro-egldevice-swrast.c owns the four EGL controls. The helper already deletes its VM on exit. A bounded concurrent observer can collect renderer journal records while the unchanged helper is alive; it must not suppress deletion or copy the collector/probe. Scope Corral HOME/XDG state to a new owned directory.

Mutter49.4 GL3 and GLES paths log GL_RENDERER after context initialization under WINSYS. cogl-debug.c lists winsys as logging-only; cogl-debug.h gates the note on the runtime flag, cogl-profile.h maps the normal trace sink to g_message, and cogl.c initializes the debug environment. Bind journal metadata to the observed live gnome-shell PID, UID, boot and start time, then join the greeter identity from the reused collector and the test-user Wayland session. Require software renderer strings and expected software-policy variables in the same actual process. Missing, stale, contradictory or hardware-renderer observations fail the comparison rather than becoming inferred success.

Admission stays cheap and fail-closed: fixed official repository identity (id1029250013, full_name tuna-os/tunaOS), exact checkout/context/input/owner-variable head equality, explicit confirmation, manual event, first attempt and no earlier run for that workflow/head. GitHub workflow-run REST supports head_sha/event filters. Missing activation must be a visible admission failure, not an all-skipped green. No activation variable, environment or secret is created now.

Future same-run transfer must bind the immutable artifact ID, API producer/run/head/attempt and independent upload digest before any extraction or image load. A bounded baseline OCI archive, coherent signed RPM sets and public key are test inputs, not production publication. Exact transport size limits and one-day retention must be explicit in the source candidate and later runtime approval. Evidence output is a separate small allowlist: sanitized reports/logs and selected screenshots, never raw Corral SSH records, keys, VM disks or ISOs.

## Files examined

- tunaos:Justfile:56-143 — supported build arguments and immutable chain override.
- tunaos:scripts/resolve-flavor.sh — source-only invocation confirmed Albacore tuna routing without a build.
- tunaos:tests/manual/luks-first-boot-contract.sh:1-32 — existing home for manual test harnesses.
- tunaos:tests/test_qualify_image_packages.py:1-105 — pytest/importlib conventions and explicit package identities.
- tunaos:.github/scripts/tuna-pr-build-inputs.sh:5-14 — unchanged automatic image admission.
- tunaos:.github/workflows/qualify-image-packages.yml:18-145 — manual-only orchestration, fixed budgets and fatal build statuses.
- reference:mock/alma10-ci.cfg:11-107 — immutable bootstrap is not an immutable dependency snapshot.
- reference:scripts/run-alma-rpm.sh:71-90 — native dependency setup, macros and inventory capture.
- reference:scripts/candidate-rpm-repository.py:36-110 — temporary signing and isolated signature verification.
- #3974:scripts/gdm-login-gate.sh:37-103,245-270,385-463 — four controls, diagnostic-only swallowing, visible transition gate.
- #3974:scripts/greeter-graphics-evidence.sh:107-238 — greeter selection and PID/start-time identity checks; reuse its selected process output rather than inventing another collector.
- #3974:scripts/corral-boot-gate.sh — owns boot and VM deletion; no cleanup-suppression wrapper.

## External references

- https://github.com/GNOME/mutter/blob/49.4/cogl/cogl/driver/gl/gl3/cogl-driver-gl3.c — GL_RENDERER WINSYS note at570-579.
- https://github.com/GNOME/mutter/blob/49.4/cogl/cogl/driver/gl/gles2/cogl-driver-gles2.c — same GLES note at756-765.
- https://github.com/GNOME/mutter/blob/49.4/cogl/cogl/cogl-debug.c — winsys is a non-behavioral logging option and reads COGL_DEBUG.
- https://github.com/GNOME/mutter/blob/49.4/cogl/cogl/cogl-debug.h — runtime debug-note guard.
- https://github.com/GNOME/mutter/blob/49.4/cogl/cogl/cogl-profile.h — non-profile trace fallback to g_message.
- https://github.com/GNOME/mutter/blob/49.4/cogl/cogl/cogl.c — debug environment initialization.
- https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow — bounded workflow/head/event selection and first-attempt provenance.
- https://github.com/tuna-os/tunaOS/issues/3969#issuecomment-6476835449 — independently verified source/patch identity and clean application; do not repeat it for green.

## Prior plans / specs consulted

- Specification20261029021133-a6425a90-mesa-3969-isolated-comparison, read through the CLI — source-only scope, complete path and explicit runtime hold.
- Plan20261020002748-iso-artifact-transport-adapter, read through the CLI — immutable independently reviewed policy, exact selected producer and conservative first-attempt checks. Its completed-run media adapter cannot be reused unchanged for a live same-run lab transfer; do not change or claim to replace it.
- Prior ISO parity implementation metadata in the user's checkout is historical only, not runtime evidence and not changed here.

## Open assumptions

No unverified runtime fact is treated as implementation permission or success. Before a future experiment, admission must establish the exact reviewed head; build preflight must establish the affected Mesa source/version, free space and toolchain; runtime must establish KVM, complete artifact identity and real renderer/desktop evidence. Missing facts produce named refusals. Actual package build duration, binary sizes, target distribution logging and resource availability remain unmeasured. The existing build-amd64 runner is currently unassigned for the separate engine iso-smoke job; no availability or fallback claim is made.

## Drafting assumptions

### Manual immutable-container lab (architecture)
- **Decision**: Choose a small manual harness with one frozen dependency-complete build image, one baseline and unchanged pinned guest helpers.
- **Rationale**: Preserves the fixed comparison without importing production factory trust/publication policy or building a new mock snapshot subsystem.
- **Rejected**: A factory adapter couples this lab to unrelated production controls; a standalone mock snapshot adds repository and root-cache lifecycle.

### Conventions selected (architecture)
- **Decision**: Apply effect-based evidence, unchanged gates, reviewed inputs, owned cleanup, pytest/just checks, current-main review and precise documentation.
- **Rationale**: These govern the touched source, trust and qualification surfaces. No existing gate is renamed or generated production format changed.
- **Rejected**: Loading every convention into the implementation without a relevant affected surface.

### Bounded binary transport, not publication (architecture)
- **Decision**: Declare a 24GiB archive, 32GiB unpacked input cap, one-day retention and separate 32MiB evidence cap.
- **Rationale**: Complete same-run inputs need authenticated transfer; limits are explicit upper bounds, not measured sizes or runtime permission.
- **Rejected**: Production registry publication, unbounded uploads, private keys, disks and ISO transport.

### Isolated frozen build container (discovery)
- **Decision**: Install build dependencies once and freeze a local immutable image for both full Mesa builds.
- **Rationale**: Same measured root/toolchain without changing production package-factory policy or trusting moving repo URLs.
- **Rejected**: Two independent mock initializations or a new production publisher lane.

### Existing helper plus renderer observer (discovery)
- **Decision**: Keep pinned probe/collector/GDM/cleanup code unchanged; add only bounded actual-renderer observation while the helper runs.
- **Rationale**: Upstream Cogl has a logging-only GL_RENDERER path; environment-only inference is insufficient.
- **Rejected**: Duplicate collector, loader shim, swallowed crash, longer gate or cleanup suppression.

### Source-only implementation, no activation (discovery)
- **Decision**: New genuine manual test files and a standalone dispatch workflow; no production image-input or default-routing edits.
- **Rationale**: Owner approved source preparation and safety scenarios, not another runtime campaign.
- **Rejected**: Dispatching for proof, creating protected settings or bypassing automatic image gates.

### Collect controls before the display manager (components)
- **Decision**: A lab-only boot unit executes the pinned C probe once per environment before GDM; keep the helper's optional second probe path unset.
- **Rationale**: A software-forced negative control can fail before the login helper is reached. Early structured collection preserves all four outcomes without a second VM, a probe/login race or cleanup suppression.
- **Rejected**: Waiting for an unreachable greeter, duplicating the C probe, pausing the gate, suppressing deletion or adding extra probe guests.

### Preserve actual software policy (components)
- **Decision**: Keep the existing 60-tunaos-software-gl generator intact, add logging-only Cogl diagnostics and the same explicit software-forced GDM test condition to both owned lab images.
- **Rationale**: The current production generator exports LIBGL_ALWAYS_SOFTWARE=1 for no-3D user sessions; it does not export a swrast override. The four probe controls remain separate.
- **Rejected**: Removing the generator, globally forcing a different driver or accepting unforced normal GDM as repair proof.

## Rehydration cues

Resume this plan at discovery/architecture through Spektacular; never reset the user's older ISO workflow. Re-read the input contract and current helper source before changing shared interfaces. Review local://mesa-source-research-contract.md and the retained primary-source links. Planning self-approval covers only the already approved source preparation. No Mesa build, signing key, guest or dispatch may run before later exact-head approval.

## Implementation findings and owner update

The native wrapper at scripts/build-image-inner.sh:217-232 unconditionally retries and can globally remove Buildah containers. A no-retry owned-only lab therefore uses one direct unchanged native Containerfile build, with exact git archive and the existing scripts/config.py generate --root API for ignored adapters, rather than invoking or patch-copying that wrapper. The generator is canonical; this is not a production engine fork.

The owner explicitly moved every build/test verification to CI. No local builds or tests may run, including source smokes. Source-only hosted checks remain authorized; Mesa runtime, keys, guests, dispatch, activation and production operations remain held.
