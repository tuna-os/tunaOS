# Bounded ISO desktop qualification candidate

This candidate extends `feat/iso-parity-cutover` at `3e61b0e0`.
It adds an opt-in path for `bonito:xfce:linux/amd64`.
It does not admit XFCE into production qualification or activate a schedule.
The evidence names OSTree; it cannot prove native-composefs or physical GPU support.

## Inventory and preflight

The inventory reads validated TOML and the required platform policy:

```sh
python3 scripts/plan-iso-qualification.py | jq .
python3 scripts/plan-iso-qualification.py \
  --target bonito:xfce:linux/amd64 --max-parallel 1 --candidate-xfce
```

It retains configured rows and required obligations as separate fields.
A missing architecture remains an obligation.
A conflict with CPU policy blocks the target.
Skipjack GNOME/v2 conflicts with the Stream 10 baseline.
The ordinary AMD64 rows for Alma conflict with its v2 policy.
The configuration owner must resolve these conflicts; the planner does not omit them.

Each flavor retains its full name and NVIDIA suffix.
NVIDIA needs physical GPU evidence. A headless image has no GUI to test.
TunaOS#3200 owns admission of `hummingbird:tuna`; package prerequisite #832 has closed.
Do not repeat that package work or count tuna as runnable.

Ordinary campaigns select at most four targets, with concurrency one or two.
The XFCE candidate accepts only Bonito on AMD64.
A native artifact can serve only its exact target.
All inventory results remain `unrun` until a runtime run produces evidence.

## Immutable frontend mapping

The source is `tuna-os/bootc-installer` at
`9259ef88876f0eabab2499edaf09829ded5dc609`, under `frontends/xfce`.
The parent verified this mapping in the [immutable Flatpak index](https://github.com/tuna-os/docs/blob/4f99596e94f2c3c473e076ae8446b6a7721d10cd/static/flatpak/index/static).

| Field | Value |
|---|---|
| Application | `org.tunaos.InstallerXfce` |
| Flatpak commit | `2de0ddf67b8f26a90bb49e8ad837044986db95b333e734683d7da4c4ea29e3ad` |
| AMD64 OCI digest in index | `sha256:a0f781c5f3ee1df63edc474e660093485dab397cb9a3b4e692a0cda22ac2a718` |
| Bundled Fisherman source | `02ac7097abb07a206479ea84a559c41db12bf629` |

The index is source evidence, not proof of installed bytes.
Before GUI input, the live probe reads `flatpak info --show-commit`, `flatpak ps`,
and `/etc/tunaos/live-installer-info`. All must match the reviewed application and commit.
A later update from the remote fails this check; it cannot silently change the wizard.

The GUI invokes the host's `/usr/local/bin/fisherman`.
`customize-live.sh` links this path to the installed frontend's bundled binary.
The probe checks that its resolved path equals the binary under the exact deployed
`flatpak info --show-location` directory, then records the executable's SHA-256.
Both install modes must observe the same digest.
Do not infer its source revision from the Flatpak manifest.

The obsolete `tuna-installer-xfce` URL returned `Repository not found` during the initial audit.
No retry or credential change followed. The verified source in the unified repository resolved that access gap.

## Executable path

The future bounded campaign uses these Live ISO workflow inputs:

```yaml
variant: bonito
flavor: xfce
platform: linux/amd64
candidate_xfce: true
build_runner: github
```

The workflow builds one artifact and passes its same-run identity to the reusable test.
After normal artifact admission, the candidate entry point is:

```sh
python3 scripts/run-xfce-candidate.py \
  --iso "$ISO_PATH" --output iso-e2e-out/xfce-candidate
```

This command needs the provenance variables from the same-run workflow.
It refuses missing inputs, a changed ISO, a different producer revision, or an occupied output directory.
Do not dispatch this campaign before parent review.

The existing harness creates fresh plain and LUKS disks.
It retains detached cold/warm boots and unmodified kernel arguments.
The XFCE driver uses real pointer and key events through these source-defined pages:
welcome, source, destination, setup, identity, confirm, progress, done.
It selects live self-install and fills the actual identity widgets.
It verifies the target disk, account, hostname and encryption in the GUI summary before submission.
It never invokes Fisherman directly or writes a recipe.

XFCE does not consume the GNOME recipe file.
For live self-install, its GUI emits `image=""` and creates the account through its widget values.
The installed source digest and publication reference must match the admitted media's source.
The GNOME recipe is not a source of this proof.

## Authenticated observation and receipts

The live probe authenticates `liveuser` over the live ISO's UART.
The ISO already boots with `console=ttyS0`; this does not establish an installed login.
No repository configuration establishes a QEMU guest agent or serial getty.

After GDM login, the installed observer switches to VT3.
It needs visible login, password and shell prompts before each input.
It authenticates the account that the GUI created, then asks sudo for authorization.
The sudo prompt has a fresh token that does not appear in command echo.
The password goes only through keyboard events after that prompt appears.
Authentication screenshots exist only in a temporary directory.

The fixed observer travels as compressed data in a bounded shell variable.
Python checks its SHA-256 before execution; no guest script file is necessary.
It checks `SUDO_USER`, finds that user's existing graphical session and its VT,
restores that VT with `chvt`, and waits for the graphical session to become active.
Only then can the observation pass. Serial carries a bounded JSON response with
fresh nonce frames; the installed guest needs no serial login.
The text session exits after the observer completes.

The run fails if the VT login or serial output is absent, sudo denies access,
or the graphical session does not become active. The harness never creates a getty, account or session
through a headless installer. It does not change installed boot arguments.

The driver logs in through GDM after each detached boot.
The observer checks the active graphical session, account UID, desktop process and its session scope.
It also reads the boot ID, source digest, publication reference and OSTree kernel argument.
The fresh boot's serial log supplies the matching XFCE desktop-contract result.
A console session is not a graphical login.

All four boot IDs must differ. A cold/warm pair must retain the same account UID.
Missing login, source, desktop contract or backend evidence fails the candidate.
There is no advisory success or substituted readiness result.

Account names use a digest in exported receipts.
Passwords stay in process memory and GUI input; recipes go through the real frontend's stdin path.
The candidate does not export raw logs from the console or screenshots as workflow artifacts.
It exports the bounded JSON observations and candidate report.
Raw captures remain in the private runner output for that run.

`NativeISOQualificationCandidate/v3` has separate `emit-candidate` and `validate-candidate` commands.
Normal `validate` rejects these receipts. Production GNOME v2 keeps its guard.
The emitter preserves the original artifact binding and labels the extra target fields as consumer observations.
A successful candidate report still says `qualified: false`.
It means the opt-in contract passed; production admission needs separate review.

## Inert checks and remaining runtime proof

Run the pure recipe-boundary check against the pinned source checkout:

```sh
python3 scripts/check-xfce-source-contract.py /path/to/bootc-installer
```

It extracts only pure recipe functions from the exact source revision.
It tests live self-install and account creation for both modes, without GTK, disks or a guest.
It does not reuse the frontend's no-user canary as account coverage.
Local tests substitute the command boundary of the harness and its console transport.
They drive the eight-page contract through emission and validation, with negative controls.

The actual ISO campaign remains unrun.
The pinned GUI requests `wheel`. Fisherman `02ac7097` checks each group
against the target's `etc/group`, then invokes the target's `useradd` through chroot
for OSTree. It retains each existing group and warns for each absent group.
Its source fixture `TestCreateUserSkipsMissingGroups` covers both behaviors.
The recipe is supported by that source; actual account creation remains runtime proof.

No headless account workaround changes that behavior.
The runtime run must also prove live serial login, installed VT/sudo access, GDM input geometry,
XFCE session scope and unchanged LUKS boot arguments.
Any failure remains a failure report; none counts as cutover proof.

KDE, COSMIC, Niri, Pantheon, ARM64 and physical GPU qualification remain separate gaps.
Preserve the existing diagnostic and storage owners and their branches.

## Producer compatibility correction

The earlier Grouper proposal was incorrect: its Ubuntu backend is outside this
producer's OSTree contract. The candidate now selects only Bonito/XFCE/AMD64.
`resolve-flavor.sh` maps it to `Containerfile.el10`, which disables composefs in its prepare-root configuration. The Fedora XFCE manifest selects GDM; EL10 Albacore/Yellowfin
override it with greetd, a greeter outside this candidate.
The validator accepts X11 and Wayland for XFCE with the same UID/process/scope checks.

The native producer flow is:

1. `just build bonito xfce linux/amd64 1 xfce` creates `localhost/bonito:xfce`.
2. The workflow measures its raw manifest and builds the pinned live overlay.
3. Only the final customization receives `TUNAOS_XFCE_CANDIDATE=1`.
   The first overlay stage disables the adapter.
4. `build-iso-tacklebox.sh` exports the base by digest using
   `skopeo copy --preserve-digests`. `xfce-media-input.py` verifies blob sizes and
   hashes, exact manifest and Linux/AMD64 config, then writes Fisherman's existing
   MediaInput v1. Final customization embeds the OCI layout at
   `/usr/lib/tunaos/xfce-candidate-oci` and verifies it again.
5. The separate OSTree store still must preserve the original manifest digest.
   The candidate retains that gate and the exact artifact admission.
6. The XFCE GUI emits its empty-image recipe and account. Fisherman
   `02ac7097` resolves the host descriptor and checks the layout before it partitions the disk.
   It passes the OCI source and `ghcr.io/tuna-os/bonito:xfce` update ref to bootc.
   OCI transport does not enable composefs.
7. Same-run artifact ID, archive digest and source SHA reach the reusable test.
   The candidate runner checks its ISO hash binding. Live descriptor and
   installed session source must match the measured base digest.

Pinned native Tacklebox `d3070b5` builds the store but does not write MediaInput;
its separate pure builder does. The source for XFCE needs this descriptor for every cell. This adapter uses the existing Fisherman contract and
leaves browser/storage owners untouched. It duplicates payload storage as OCI
plus the original store.
 Candidate-only ceilings are 4 GiB for the extra OCI
payload and 10 GiB for the final ISO. These limits do not assert that media fits.

The adapter measures the source blobs before export and the actual files before
it embeds them. It rejects unexpected files as well as size overruns.
The workflow checks the final ISO before upload. Each gate reports measured bytes
and its limit; an oversize result fails. Production defaults stay unchanged.

The added content consists only of OCI metadata and referenced image blobs, not
repository source. Runner capacity and actual final size remain unmeasured.

The proxy blocked access to
`git.sr.ht/~kennylevinsen/gtkgreet` (CONNECT 403). No retry or alternate route followed. Bonito's GDM
path does not depend on it. EL10 greeter work remains separate.

## Browser coverage gap

The parent supplied evidence from [issue #3797](https://github.com/tuna-os/tunaOS/issues/3797#issuecomment-6402274039).
Run `40226451044` at `e12248c7` stopped before ISO creation.
The catalog blocked Skipjack/GNOME because it lacked qualification.
There is no guest test or ISO/hash receipt from that run. Browser parity remains unproven.

That path needs a separate test-only build and retention route.
Its frontend drops fields for identity and uses harness `e89bf562`.
Preserve its existing owner and probe.
The pinned tacklebox already has `ObservedBuildResult`; do not duplicate it.
Browser bootstrap diagnostics are not strict native qualification.
