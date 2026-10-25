# Bounded ISO desktop qualification candidate

This work uses `feat/iso-parity-cutover` at `3e61b0e0`.
The source audit also checked main at `bd5aa99b`.
No runtime result or schedule change comes from this candidate.
Preserve the separate diagnostic and storage branches.
The evidence names OSTree and cannot prove native-composefs support.

## Inventory and preflight

The inventory reads validated TOML and the required platform policy:

```sh
python3 scripts/plan-iso-qualification.py | jq .
```

It retains both configured rows and required obligations.
Each row has separate `required`, `configured`, `gaps`, and `result` fields.
A missing architecture remains an obligation.
A conflict with CPU policy blocks the target.
For example, skipjack GNOME/v2 conflicts with the Stream 10 baseline.
The ordinary AMD64 rows for Alma conflict with its v2 policy.

The JSON exposes those conflicts for the configuration owner to resolve.
It does not map them to different targets without review.
The full name of each flavor retains its NVIDIA suffix.
NVIDIA needs physical GPU evidence.
A headless image has no GUI to test.

TOML defines the configured Hummingbird flavors.
TunaOS#3200 owns admission of `hummingbird:tuna`.
Package prerequisite tunaos-packages#832 has closed.
Do not repeat that package work or count tuna as runnable.

A campaign selects one to four targets, with concurrency one or two.
Native artifact consumption selects exactly one target per artifact.
Live ISO production checks the explicit platform before a build.
It rejects unsupported targets and does not start an all-cell wave.
Readiness checks retain their existing meaning.

## Evidence and observation

`NativeISOQualification/v2` retains its GNOME guard.
The emitter names OSTree and uses the CPU policy for each variant.
`NativeISOQualificationCandidate/v3` has a separate validation command.
The `validate` command rejects receipts from the candidate.

The candidate contract for GNOME, KDE, and XFCE needs:

- Immutable inputs and artifact identity from the same run.
- Fresh plain and LUKS installs, with detached cold and warm boots.
- Unmodified boot arguments and the exact reference of the installed publication.
- Full flavor, architecture, CPU baseline, source and backend identity.
- A local user session that is active, with the correct desktop process.
- A process UID and scope that match the selected login session.
- Four distinct boot IDs, each tied to its install mode and source.
- The desktop's installer identity and complete GUI transitions.

The read-only guest observer is `scripts/observe-iso-session.py`.
It reads the desktop journal, logind session, process scope and bootc identity.
It rejects a greeter, missing login, or failed desktop contract.
The tests use mock commands and a temporary process tree.
They do not execute guest commands on the host.

A checksum is not proof of authentic observations.
A trusted producer must collect them before runtime admission.

## Exact prerequisites for the XFCE path

The proposed first cell is `grouper:xfce:linux/amd64`, with concurrency one.
TOML configures its ISO. The source documents its LightDM path in
`scripts/iso-e2e.sh`, beside the installed desktop checks.
The XFCE adapter also supports Wayland on other bases; do not assume X11 there.

The strict frontend source is unavailable in this environment.
`docs/INSTALLER-FRONTENDS.md` names `tuna-os/tuna-installer-xfce`.
An ordinary clone returned `Repository not found` on 2026-10-25.
No alternate route or credential change followed that response.
To proceed, provide a local checkout or the current authorized repository.

The missing component must supply the actual wizard and user-account behavior.
The live adapter installs `org.tunaos.InstallerXfce` from the Flatpak remote.
It does not use the pinned GNOME bundle.
The existing ordered driver controls GNOME's different frontend.
It cannot truthfully emit an XFCE receipt.

The existing session-login helper also cannot serve as strict transport.
It disables checks of the SSH host key and treats missing SSH as advisory by default.
Its test account comes from the recipe for headless Fisherman installs.
The strict GUI path does not call that recipe path.
The frontend must therefore establish an account before an installed login test.
Do not inject the headless recipe to bypass this prerequisite.

After source access, add the XFCE driver and authenticate observation transport.
Then test the full producer flow with inert fixtures and get independent review.
The smallest campaign uses Grouper with XFCE, in both install modes.
No runtime dispatch has occurred. The XFCE path is not complete yet.
COSMIC, Niri, Pantheon, ARM64 and physical GPU qualification remain separate gaps.

## Browser coverage gap

The parent supplied evidence from [issue #3797](https://github.com/tuna-os/tunaOS/issues/3797#issuecomment-6402274039).
Run `40226451044` at `e12248c7` stopped before ISO creation.
The catalog blocked Skipjack/GNOME because it lacked qualification.
There is no guest test or ISO/hash receipt from that run.
Browser parity remains unproven.

That path needs a separate test-only build and retention route.
Its frontend drops fields for identity and uses harness `e89bf562`.
Preserve its existing owner and probe.
The pinned tacklebox already has `ObservedBuildResult`; do not duplicate it.
Browser bootstrap diagnostics are not strict native qualification.
