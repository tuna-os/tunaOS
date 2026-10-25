# Bounded ISO desktop qualification candidate

This candidate extends `feat/iso-parity-cutover` at `3e61b0e0`.
It adds an opt-in path for `grouper:xfce:linux/amd64`.
It does not admit XFCE into production qualification or activate a schedule.
The evidence names OSTree; it cannot prove native-composefs or physical GPU support.

## Inventory and preflight

The inventory reads validated TOML and the required platform policy:

```sh
python3 scripts/plan-iso-qualification.py | jq .
python3 scripts/plan-iso-qualification.py \
  --target grouper:xfce:linux/amd64 --max-parallel 1 --candidate-xfce
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
The XFCE candidate accepts only Grouper on AMD64.
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

The GUI invokes the host's `/usr/local/bin/fisherman`, not the bundled executable.
The probe records the host executable's SHA-256 separately.
Both install modes must observe the same digest.
Do not infer its source revision from the Flatpak manifest.

The obsolete `tuna-installer-xfce` URL returned `Repository not found` during the initial audit.
No retry or credential change followed. The verified source in the unified repository resolved that access gap.

## Executable path

The future bounded campaign uses these Live ISO workflow inputs:

```yaml
variant: grouper
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

The transport uses a Unix socket for the harness-owned QEMU UART.
It authenticates `liveuser` only for the live probe.
Installed observation authenticates the account created through the GUI.
It does not use SSH, disable host-key verification, use sudo, or inject a guest file.
Responses have fresh nonce frames. Echo from the terminal cannot impersonate a result.

The driver logs in through LightDM after each detached boot.
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
The pinned GUI requests the `wheel` group; Grouper must prove account creation under its real group policy.
No headless account workaround changes that behavior.
The runtime run must also prove serial login, unprivileged bootc status, LightDM input geometry,
XFCE session scope and unchanged LUKS boot arguments.
Any failure remains a failure report; none counts as cutover proof.

KDE, COSMIC, Niri, Pantheon, ARM64 and physical GPU qualification remain separate gaps.
Preserve the existing diagnostic and storage owners and their branches.

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
