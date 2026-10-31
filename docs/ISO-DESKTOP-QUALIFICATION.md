# Bounded ISO desktop qualification candidate

This candidate merges `feat/iso-parity-cutover` at `cf04a15e` and retains its original `3e61b0e0` ancestry.
It adds an opt-in path for `bonito:xfce:linux/amd64`.
It does not admit XFCE into production qualification or activate a schedule.
The evidence names OSTree; it cannot prove native-composefs or physical GPU support.

## Inventory and preflight

The inventory reads validated `tunaos.toml` through `lib.tunaos_config`.
A flavor platform list replaces the variant list. `build_image` declares source
image support; `build_iso` selects the ISO inventory. Global platforms do not
create missing architecture obligations:

```sh
python3 scripts/plan-iso-qualification.py | jq .
python3 scripts/plan-iso-qualification.py \
  --target bonito:xfce:linux/amd64 --max-parallel 1 --candidate-xfce
```

The current inventory has 62 flavor pairs and 92 configured platform rows.
The removed preview policy had inferred 97 obligations and a 108-row union.
That proposal does not define the current support contract. The merged
base removes that policy; this candidate does not restore it or invent ARM64
rows.

A future wider commitment needs an explicit owner-approved contract.
All configured rows remain visible, including disabled source images and CPU
baseline conflicts. Bare Alma AMD64 and its v2 builds keep distinct identities.
Skipjack GNOME/v2 remains configured but blocked by the native baseline check.

Each flavor retains its full name and NVIDIA suffix.
NVIDIA needs physical GPU evidence. A headless image has no GUI to test.
TunaOS#3200 owns admission of `hummingbird:tuna`; package prerequisite #832 has closed.
Do not repeat that package work or count tuna as runnable.

Ordinary campaigns select at most four targets, with concurrency one or two.
The XFCE candidate accepts only Bonito on AMD64.
A native artifact can serve only its exact target.
All inventory results remain `unrun` until a runtime run produces evidence.

The merged workflow keeps the owner’s readiness check for PRs and schedules.
Strict qualification runs only for a native artifact. The producer calls it
only on manual dispatch: GNOME, or the explicit Bonito/XFCE/AMD64 candidate.
The owner’s summary reads each candidate leg from the XFCE output directory.
It does not turn that report into production qualification.

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
The candidate exports only its bounded directory for diagnostics.
It includes JSON receipts, the harness log, serial logs with known credentials removed, and welcome
screenshots copied before any credential input. The collector removes terminal
control codes before it removes known account names and passwords.
Other screenshots and raw captures stay in the private runner directory.

The harness stdout is private; it cannot print output from guests into Actions logs.
Helpers for LUKS receive passwords through stdin, after removal of passwords from the environment. Their serial output removes a password even across successive reads.

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

Workflow fixtures also exercise candidate selection and strict exit status.
They check access to KVM as root for the candidate. Ordinary modes retain
their KVM/TCG choice through sudo.
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
 Candidate-only ceilings are 8 GiB for the extra OCI
payload and 10 GiB for the final ISO. These limits do not assert that media fits.

The OCI ceiling bounds uncompressed bytes: `--preserve-digests` keeps the
containers-storage layers uncompressed. Run `40546860986` measured bonito:xfce
at 6478177651 bytes and failed the earlier 4 GiB ceiling (#3997).

The adapter measures the source blobs before export and the actual files before
it embeds them. It rejects unexpected files as well as size overruns.
The workflow checks the final ISO before upload. Each gate reports measured bytes
and its limit; an oversize result fails. Production defaults stay unchanged.

The added content consists only of OCI metadata and referenced image blobs, not
repository source. Runner capacity and the final ISO size remain unmeasured.

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

## Launch limits after the pre-launch review

The maintainer selects the inputs above on `codex/iso-desktop-expansion`.
Candidate runs use the same key for the queue and do not cancel an active candidate.
The reusable consumer uses a separate queue key to avoid a caller deadlock.
The matrix has one cell and `max_parallel: 1`.

| Job | Limit | Internal limits |
|---|---|---|
| Producer preflight | 5 minutes | Install pinned yq, then validate the one target |
| Producer build | 160 minutes | OS build 50; Live ISO 85; 25 left for setup and upload |
| Consumer matrix | 5 minutes | Install pinned yq before the planner |
| Consumer test | 160 minutes | Artifact download/extract at most 70; strict step 60; 30 left for setup and export |

The step for Live ISO limits customization of the overlay at 30 minutes and ISO engine work
at 40 minutes. Each has a two-minute kill grace. The step has nine minutes left
for other work and two minutes for forced termination. These limits apply only to the candidate.
The consumer uses QEMU packages from apt. The conflict between `.16` and `.18` pins in the diagnostic branch does not apply to this path.

The strict supervisor has a 3300-second deadline. Its Linux child subreaper
also owns children of detached daemons. Cleanup and private log drain have at most four 15-second waits;
diagnostic collection has 120 seconds. This fits the 3600-second step.

The harness has a shared 3240-second deadline. GUI input, observation and LUKS unlock each use the lesser of their phase cap and the time left.
Each reserves five seconds for forced termination.

The caps are 610, 300 and 240 seconds; they are not separate time reservations.
Readiness waits are 180 seconds. All plain/LUKS cold/warm legs remain required.
An exhausted budget fails the campaign; it cannot count a skipped leg as success.

No measurement yet proves that these caps fit an actual installation.

Preflight needs yq before publication resolution. The build and consumer need
at least 12 GiB available RAM and four available CPUs.
The VM stays at 8 GiB and four vCPUs, with 4 GiB for QEMU and OCR on the host.

The producer needs 52 GiB free disk: three 8 GiB payload copies, two 10 GiB ISO
copies and 8 GiB scratch. The consumer needs 56 GiB before download: a 12 GiB
archive, 10 GiB ISO, 10 GiB extraction, 16 GiB installed writes and 8 GiB scratch.
It checks for 24 GiB free again before the VM sequence.

These are admission floors, not measured consumption or a guarantee against disk
exhaustion. The two 64 GiB virtual disks are sparse; preflight does not reserve
their full logical capacity.

A stock hosted runner may not meet these floors. If it fails, choose enough
runner capacity through a reviewed change before launch; do not remove the check.
The consumer now uses `ubuntu-24.04`.

Diagnostics retain at most 256 files, 16 MiB per file and 128 MiB total for seven
days. The collector omits and counts oversize files. ISO and OCI ceilings stay at
10 GiB and 8 GiB; measured sizes remain required before upload.
Inert tests exercise the calls to both helpers, malformed or absent stdin, and
serial echo split across reads. They also check secret removal, shared deadlines,
cleanup of detached processes, resource floors and paths for retained files.
No VM, host package install or workflow dispatch was used for these checks.

## Candidate access isolation

The candidate skips the inherited vsock setup before it loads a module or creates a key. Both launch paths fail if arguments for vsock are nonempty.
They cannot pass the fallback's SSH credentials through SMBIOS.
Shutdown uses the monitor's ACPI command instead of SSH.
GUI account creation and the authenticated VT observer remain mandatory.

The consumer skips the inherited udev rule for world-writable KVM for this candidate.
It opens the existing `/dev/kvm` as root and checks API version 12, before package
setup and again before the harness. This check does not create a VM.
Missing access, a non-device path or an unexpected API fails the run.
The candidate refuses overrides for TCG and does not change ACLs, groups or device modes.

The ordinary jobs keep their existing behavior. Package signature checks do not change.

The producer skips the inherited subordinate-ID and AppArmor setup for candidates.
At pinned Tacklebox `d3070b5`, `rootContext()` defaults to root when EUID is zero.
`RunUnshare` then runs a shell directly; it does not call `podman unshare`.
This campaign builds as root and selects `repo=local`, so it also skips the
registry path's pull into the original user's store.

Both candidate calls set `TACKLEBOX_CONTEXT=root` after the sudo boundary,
through `env`: overlay customization and ISO production.
The nested `just iso` recipe retains its existing `sudo -E` call.
Ordinary modes still run the original setup and retain their context selection.

Fixtures exercise both boundaries with a contradictory inherited `user` context
and with context removed by the sudo stub. Neither can select rootless work
for the candidate. Negative controls remove each override and reject the result.
No package source, signature check or source/account gate changes.
